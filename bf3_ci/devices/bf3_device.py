# bf3_ci/devices/bf3_device.py

import logging
import time
import paramiko
from bf3_ci.transport.ssh import SSHTransport
from bf3_ci.devices.bmc_device import BMCDevice

logger = logging.getLogger(__name__)


class BF3Device:
    """Represents a BlueField-3 DPU."""

    def __init__(self, config: dict):
        self.name = config["name"]
        self.config = config
        self.arm_ssh = SSHTransport(
            host=config["arm"]["ip"],
            user=config["arm"]["user"],
            key_path=config["arm"].get("key"),
            password=config["arm"].get("password"),
        )
        self.bmc = BMCDevice(config["bmc"])

    def connect(self):
        try:
            self.arm_ssh.connect()
        except paramiko.AuthenticationException:
            logger.warning(
                "ARM SSH auth failed (password may be expired)")
        except ConnectionError:
            logger.warning("ARM SSH not available")
        self.bmc.connect()

    def disconnect(self):
        self.arm_ssh.disconnect()
        self.bmc.disconnect()

    def is_alive(self) -> bool:
        return self.arm_ssh.is_alive()

    def wait_for_boot(self, timeout: int = 600) -> bool:
        return self.arm_ssh.wait_for_ssh(timeout=timeout)

    def execute(self, command: str, timeout: int = 60):
        return self.arm_ssh.execute(command, timeout=timeout)

    def setup_post_install_access(self) -> bool:
        """Set up root SSH access after a fresh BFB install.

        Fresh Ubuntu BFBs default to ubuntu/ubuntu with forced
        password change and root login disabled. This method:
        1. Connects as default BFB user via password auth
        2. Handles PAM forced password change via PTY (server
           disconnects after change)
        3. Reconnects as default user with new password
        4. Runs sudo commands to enable root SSH
        5. Reconnects as root
        """
        arm_cfg = self.config["arm"]
        default_user = arm_cfg.get("default_user", "ubuntu")
        default_pw = arm_cfg.get("default_password", "ubuntu")
        target_user = arm_cfg.get("user", "root")
        target_pw = arm_cfg.get("password", "")
        temp_pw = "CiTmpPassw0rdXk92024"

        logger.info(
            f"Setting up post-install access via "
            f"{default_user}@{arm_cfg['ip']}")

        # --- Phase 1: change the expired password via PTY ---
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=arm_cfg["ip"],
                port=22,
                username=default_user,
                password=default_pw,
                timeout=30,
                allow_agent=False,
                look_for_keys=False,
            )
            logger.info(
                f"Password auth succeeded for {default_user}")
        except paramiko.AuthenticationException:
            logger.error(
                f"Password auth failed for {default_user} "
                f"(password may be wrong)")
            return False
        except Exception as e:
            logger.error(f"SSH connect as {default_user} "
                         f"failed: {e}")
            return False

        try:
            transport = client.get_transport()
            chan = transport.open_session()
            chan.get_pty(width=200)
            chan.invoke_shell()

            def _read_until(keywords, timeout: float = 10.0,
                            ) -> str:
                """Read until one of keywords appears or timeout."""
                out = ""
                deadline = time.time() + timeout
                while time.time() < deadline:
                    if chan.recv_ready():
                        out += chan.recv(4096).decode(
                            errors="replace")
                        low = out.lower()
                        for kw in keywords:
                            if kw in low:
                                return out
                    else:
                        time.sleep(0.3)
                return out

            banner = _read_until(
                ["current", "(current)", "new password"],
                timeout=15.0)
            logger.info(f"PTY banner: {banner[:300]!r}")

            if ("current" in banner.lower()
                    or "password" in banner.lower()):
                chan.send(default_pw + "\n")
                prompt = _read_until(
                    ["new password"], timeout=10.0)
                logger.info(f"PTY after current pw: "
                            f"{prompt[:200]!r}")

                chan.send(temp_pw + "\n")
                prompt = _read_until(
                    ["retype", "again", "bad password",
                     "new password"],
                    timeout=10.0)
                logger.info(f"PTY after new pw: "
                            f"{prompt[:200]!r}")

                if "bad password" in prompt.lower():
                    logger.warning("PAM rejected temp password, "
                                   "retrying")
                    chan.send(temp_pw + "\n")
                    prompt = _read_until(
                        ["retype", "again"], timeout=10.0)
                    logger.info(f"PTY retry: {prompt[:200]!r}")

                chan.send(temp_pw + "\n")
                prompt = _read_until(
                    ["updated", "$", "#", "passwd"],
                    timeout=10.0)
                logger.info(f"PTY after retype: "
                            f"{prompt[:300]!r}")
                logger.info(
                    f"Password changed to temp for "
                    f"{default_user}")
        except Exception as e:
            logger.error(f"PTY password change failed: {e}")
            client.close()
            return False

        client.close()
        time.sleep(3)
        logger.info("Phase 1 done: password changed, "
                     "server disconnected (expected)")

        # --- Phase 2: reconnect with temp password, set up root ---
        time.sleep(2)
        tmp = SSHTransport(
            host=arm_cfg["ip"],
            user=default_user,
            password=temp_pw,
        )
        try:
            tmp.connect()
            logger.info(f"Reconnected as {default_user} "
                         "with temp password")
        except Exception as e:
            logger.error(f"Reconnect as {default_user} "
                         f"with temp password failed: {e}")
            return False

        if target_user == "root":
            tmp.execute(
                "sudo sed -i 's/^.*dictcheck.*/dictcheck = 0/' "
                "/etc/security/pwquality.conf; "
                "sudo sed -i 's/^.*minlen.*/minlen = 6/' "
                "/etc/security/pwquality.conf",
                timeout=10)
            logger.info("Relaxed pwquality on DPU")

            r = tmp.execute(
                f"echo 'root:{target_pw}' | sudo chpasswd",
                timeout=10)
            logger.info(f"chpasswd root: rc={r.rc}")

            r = tmp.execute(
                "sudo chage -I -1 -m 0 -M 99999 -E -1 root",
                timeout=10)
            logger.info(f"chage root: rc={r.rc}")

            r = tmp.execute(
                "sudo sed -i "
                "'s/^#*PermitRootLogin.*/PermitRootLogin yes/' "
                "/etc/ssh/sshd_config",
                timeout=10)
            logger.info(f"PermitRootLogin: rc={r.rc}")

            r = tmp.execute(
                "sudo systemctl restart sshd || "
                "sudo systemctl restart ssh",
                timeout=15)
            logger.info(f"restart sshd: rc={r.rc}")

            logger.info("Root SSH access enabled on DPU")

        tmp.disconnect()

        # --- Phase 3: reconnect as root ---
        self.arm_ssh.disconnect()
        time.sleep(2)
        try:
            self.arm_ssh.connect()
            logger.info(f"Reconnected as {target_user}")
            return True
        except Exception as e:
            logger.error(f"Root reconnect failed: {e}")
            return False

    # ??? Version Queries ?????????????????????????????

    def get_arm_os_version(self) -> str:
        result = self.execute(
            "cat /etc/mlnx-release 2>/dev/null || "
            "cat /etc/os-release | grep VERSION_ID"
        )
        return result.stdout

    def get_atf_version(self) -> str:
        result = self.execute("bfver 2>/dev/null | grep ATF")
        return result.stdout.split(":")[-1].strip() \
            if result.rc == 0 else "unknown"

    def get_uefi_version(self) -> str:
        result = self.execute("bfver 2>/dev/null | grep UEFI")
        return result.stdout.split(":")[-1].strip() \
            if result.rc == 0 else "unknown"

    def get_nic_fw_version(self) -> str:
        result = self.execute(
            "mlxfwmanager --query 2>/dev/null | "
            "grep 'FW ' | awk '{print $NF}'"
        )
        return result.stdout

    def get_cx_fw_version(self) -> str:
        """Get ConnectX-8 firmware version."""
        result = self.execute(
            "mlxfwmanager --query 2>/dev/null | "
            "grep 'FW ' | head -1 | awk '{print $NF}'"
        )
        return result.stdout

    def get_doca_version(self) -> str:
        """Get DOCA runtime version."""
        result = self.execute(
            "dpkg -l 2>/dev/null | grep doca-runtime | "
            "awk '{print $3}' || "
            "rpm -q doca-runtime 2>/dev/null"
        )
        return result.stdout if result.rc == 0 else "unknown"

    def get_bfb_version(self) -> str:
        result = self.execute("cat /etc/mlnx-release")
        return result.stdout

    # ??? eMMC ????????????????????????????????????????

    def get_emmc_info(self) -> dict:
        """Get eMMC device info."""
        info = {}
        result = self.execute("lsblk -o NAME,SIZE,TYPE /dev/mmcblk0")
        info["lsblk"] = result.stdout
        result = self.execute(
            "cat /sys/class/mmc_host/mmc0/mmc0:0001/name"
        )
        info["name"] = result.stdout
        return info

    def get_emmc_health(self) -> dict:
        """Get eMMC health/life info."""
        result = self.execute(
            "mmc extcsd read /dev/mmcblk0 2>/dev/null | "
            "grep -i 'life\\|eol'"
        )
        return {"raw": result.stdout}

    # ??? Crypto / Security ??????????????????????????

    def get_crypto_status(self) -> dict:
        """Get hardware crypto offload status."""
        status = {}

        result = self.execute(
            "mlxconfig -d /dev/mst/mt*_pciconf0 q 2>/dev/null "
            "| grep -i crypto"
        )
        if result.rc == 0 and result.stdout:
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    status[parts[0]] = parts[1]

        result = self.execute(
            "devlink dev param show pci/0000:03:00.0 "
            "name enable_crypto 2>/dev/null"
        )
        if result.rc == 0:
            status["devlink_crypto"] = result.stdout

        return status

    def is_crypto_enabled(self) -> bool:
        """Check if hardware crypto is enabled."""
        status = self.get_crypto_status()
        for key, val in status.items():
            if "crypto" in key.lower() and "enabled" in key.lower():
                return "true" in val.lower() or "(1)" in val
        result = self.execute(
            "mlxconfig -d /dev/mst/mt*_pciconf0 q 2>/dev/null "
            "| grep -i CRYPTO_ENABLED | awk '{print $2}'"
        )
        return result.stdout.strip().startswith("True")

    def get_secure_boot_status(self) -> str:
        """Check UEFI Secure Boot status."""
        result = self.execute(
            "bfver 2>/dev/null | grep -i 'secure boot'"
        )
        if result.rc == 0 and result.stdout:
            return result.stdout.strip()
        result = self.execute(
            "mokutil --sb-state 2>/dev/null"
        )
        return result.stdout.strip() if result.rc == 0 else "unknown"

    # ??? Boot Management ?????????????????????????????

    def get_boot_partition(self) -> str:
        """Get active boot partition (primary/alternate)."""
        result = self.execute("mlxbf-bootctl")
        return result.stdout

    def switch_boot_partition(self):
        """Switch to alternate boot partition."""
        result = self.execute("mlxbf-bootctl -s")
        return result.rc == 0

    # ??? Power Control ???????????????????????????????

    def power_cycle(self):
        self.bmc.host_power_cycle()

    def warm_reboot(self):
        self.execute("reboot", timeout=10)

    def cold_reboot(self):
        self.bmc.host_power_cycle()
