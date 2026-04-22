# bf3_ci/devices/bmc_device.py

import logging
import time
from bf3_ci.transport.redfish import RedfishTransport
from bf3_ci.transport.ssh import SSHTransport

logger = logging.getLogger(__name__)

NVIDIA_OEM_URI = "/Managers/Bluefield_BMC/Oem/Nvidia"
BMC_MANAGER_URI = "/Managers/Bluefield_BMC"
UPDATE_SERVICE_URI = "/UpdateService"


class BMCDevice:
    """BF3 BMC (OpenBMC) device."""

    def __init__(self, config: dict):
        self.config = config
        self.ip = config["ip"]
        self.redfish = RedfishTransport(
            host=config["ip"],
            user=config["user"],
            password=config["password"],
        )
        self.ssh = SSHTransport(
            host=config["ip"],
            user=config["user"],
            password=config["password"],
        )

    def connect(self):
        try:
            self.ssh.connect()
        except ConnectionError:
            logger.warning("BMC SSH not available")

    def disconnect(self):
        self.ssh.disconnect()

    def is_alive(self) -> bool:
        return self.redfish.is_alive()

    # ??? Firmware ????????????????????????????????????

    def get_firmware_version(self) -> str:
        data = self.redfish.get(BMC_MANAGER_URI)
        return data.get("FirmwareVersion", "unknown")

    def get_build_id(self) -> str:
        result = self.ssh.execute(
            "cat /etc/os-release | grep BUILD_ID"
        )
        return result.stdout

    def update_firmware_redfish(self, image_path: str,
                                 timeout: int = 900) -> bool:
        """Update BMC firmware via Redfish push."""
        with open(image_path, "rb") as f:
            import requests
            resp = requests.post(
                f"https://{self.ip}/redfish/v1/"
                f"UpdateService/update",
                files={"UpdateFile": f},
                auth=(self.config["user"],
                      self.config["password"]),
                verify=False,
                timeout=timeout,
            )
        if resp.status_code in (200, 202):
            task_uri = resp.json().get("@odata.id", "")
            if task_uri:
                self.redfish.wait_for_task(task_uri,
                                            timeout=timeout)
            return True
        return False

    def update_firmware_scp(self, image_path: str,
                             timeout: int = 600) -> bool:
        """Update BMC firmware via SCP + local flash."""
        self.ssh.scp_put(image_path, "/tmp/bmc-fw.img")
        result = self.ssh.execute(
            "/usr/bin/bmc-update /tmp/bmc-fw.img",
            timeout=timeout,
        )
        return result.rc == 0

    def factory_reset(self):
        self.ssh.execute("obmcutil factory-reset")

    def reboot(self):
        self.ssh.execute("reboot", timeout=10)

    def wait_for_ready(self, timeout: int = 300) -> bool:
        """Wait for BMC to be fully ready after reboot."""
        return self.redfish.wait_for_redfish(timeout=timeout)

    # ??? RShim (BF3 BMC-side) ????????????????????????

    def enable_rshim(self, timeout: int = 60) -> bool:
        """Enable BMC-side RShim via Redfish."""
        payload = {"BmcRShim": {"BmcRShimEnabled": True}}
        try:
            self.redfish.patch(NVIDIA_OEM_URI, payload)
        except Exception as e:
            logger.error(f"Enable RShim failed: {e}")
            return False
        return self._wait_rshim_state(True, timeout)

    def disable_rshim(self, timeout: int = 60) -> bool:
        """Disable BMC-side RShim via Redfish."""
        payload = {"BmcRShim": {"BmcRShimEnabled": False}}
        try:
            self.redfish.patch(NVIDIA_OEM_URI, payload)
        except Exception as e:
            logger.error(f"Disable RShim failed: {e}")
            return False
        return self._wait_rshim_state(False, timeout)

    def get_rshim_status(self) -> bool:
        data = self.redfish.get(NVIDIA_OEM_URI)
        return data.get("BmcRShim", {}).get(
            "BmcRShimEnabled", False
        )

    def _wait_rshim_state(self, expected: bool,
                          timeout: int) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.get_rshim_status() == expected:
                    return True
            except Exception:
                pass
            time.sleep(2)
        return False

    def get_rshim_service_status(self) -> str:
        """Check rshim.service status on BMC."""
        result = self.ssh.execute(
            "systemctl is-active rshim.service"
        )
        return result.stdout.strip()

    # ??? Host Power Control ??????????????????????????

    def host_power_on(self):
        self.ssh.execute("obmcutil poweron")

    def host_power_off(self):
        self.ssh.execute("obmcutil poweroff")

    def host_power_cycle(self):
        self.ssh.execute("obmcutil powercycle")

    def host_warm_reboot(self):
        self.ssh.execute("obmcutil hostreboot")

    def get_host_state(self) -> str:
        result = self.ssh.execute("obmcutil state")
        return result.stdout

    def get_smartnic_os_state(self) -> str:
        """Get DPU OS state via NCSI OEM command."""
        result = self.ssh.execute(
            "busctl get-property "
            "xyz.openbmc_project.Settings.connectx "
            "/xyz/openbmc_project/network/connectx/"
            "smartnic_os_state/os_state "
            "xyz.openbmc_project.Control.NcSi.OEM.Nvidia"
            ".SmartNicOsState SmartNicOsState"
        )
        return result.stdout

    # ??? Health ??????????????????????????????????????

    def get_sensor_readings(self) -> dict:
        result = self.ssh.execute(
            "ipmitool sensor list 2>/dev/null"
        )
        sensors = {}
        for line in result.stdout.splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2:
                sensors[parts[0]] = parts[1]
        return sensors

    def get_sel_entries(self) -> list:
        result = self.ssh.execute(
            "ipmitool sel list 2>/dev/null"
        )
        return result.stdout.splitlines()

    def clear_sel(self):
        self.ssh.execute("ipmitool sel clear")

    def get_journal_errors(self, since: str = "1h") -> str:
        """Get recent journal errors."""
        result = self.ssh.execute(
            f"journalctl --since='-{since}' -p err "
            f"--no-pager 2>/dev/null"
        )
        return result.stdout

    # ??? Network ?????????????????????????????????????

    def get_network_config(self) -> dict:
        """Get BMC network configuration."""
        result = self.ssh.execute("ip addr show")
        return {"raw": result.stdout}

    # ??? User Management ?????????????????????????????

    def get_users(self) -> list:
        """Get Redfish user accounts."""
        data = self.redfish.get(
            "/AccountService/Accounts"
        )
        return data.get("Members", [])

    def create_user(self, username: str, password: str,
                    role: str = "Administrator") -> bool:
        payload = {
            "UserName": username,
            "Password": password,
            "RoleId": role,
            "Enabled": True,
        }
        try:
            self.redfish.post(
                "/AccountService/Accounts", payload
            )
            return True
        except Exception as e:
            logger.error(f"Create user failed: {e}")
            return False

    def delete_user(self, username: str) -> bool:
        try:
            accounts = self.get_users()
            for acct in accounts:
                uri = acct["@odata.id"]
                data = self.redfish.get(
                    uri.replace("/redfish/v1", "")
                )
                if data.get("UserName") == username:
                    import requests
                    resp = self.redfish.session.delete(
                        f"https://{self.ip}{uri}",
                        timeout=30,
                    )
                    return resp.status_code in (200, 204)
            return False
        except Exception as e:
            logger.error(f"Delete user failed: {e}")
            return False
