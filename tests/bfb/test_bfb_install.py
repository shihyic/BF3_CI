# tests/bfb/test_bfb_install.py

import logging
import pytest

pytestmark = [pytest.mark.bfb, pytest.mark.destructive]

logger = logging.getLogger(__name__)

_install_ok = False


def _require_install(cls_name="TestBFBInstall"):
    """Skip if the BFB install test did not pass."""
    if not _install_ok:
        pytest.skip("BFB install did not succeed; "
                     "skipping post-install verification")


class TestBFBInstall:
    """BFB installation tests for BF3."""

    @pytest.mark.p0
    @pytest.mark.timeout(3600)
    @pytest.mark.rshim_host
    def test_install_bfb_via_host_rshim(self, bf3, host,
                                         bfb_path, timeouts):
        """BFB-001: Install BFB via host RShim."""
        global _install_ok

        if bfb_path is None:
            pytest.skip("No BFB specified")

        from bf3_ci.devices.rshim_device import RShimDevice
        rshim = RShimDevice(transport=host.ssh, source="host")

        if not rshim.is_available():
            pytest.skip("Host RShim not available")

        assert rshim.push_bfb(bfb_path), "BFB push failed"
        assert rshim.wait_for_bfb_complete(
            timeout=timeouts["bfb_complete"],
        ), "BFB install did not complete in time"
        assert bf3.wait_for_boot(
            timeout=timeouts["boot_wait"]
        ), "ARM did not become reachable after BFB install"

        result = bf3.execute("whoami", timeout=10)
        if result.rc != 0:
            logger.info(
                "ARM SSH command failed post-boot, "
                "setting up post-install access")
            assert bf3.setup_post_install_access(), \
                "Failed to set up post-install root access"

        _install_ok = True

    @pytest.mark.p0
    def test_verify_arm_os(self, bf3):
        """BFB-003: Verify ARM OS post-install."""
        _require_install()
        version = bf3.get_arm_os_version()
        assert version, "Could not get ARM OS version"

    @pytest.mark.p0
    def test_verify_all_fw_versions(self, bf3, bmc):
        """BFB-004: Verify all FW versions populated."""
        _require_install()
        assert bf3.get_uefi_version() != "unknown"
        assert bf3.get_atf_version() != "unknown"
        assert bf3.get_nic_fw_version()
        assert bmc.get_firmware_version() != "unknown"

    @pytest.mark.p0
    def test_verify_network_interfaces(self, bf3):
        """BFB-005: Verify default network config."""
        _require_install()
        required = ["tmfifo_net0", "oob_net0", "p0"]
        optional = ["p1"]
        for iface in required:
            result = bf3.execute(f"ip link show {iface}")
            assert result.rc == 0, f"{iface} not found"
        for iface in optional:
            result = bf3.execute(f"ip link show {iface}")
            if result.rc != 0:
                logger.info(f"{iface} not present "
                            "(single-port DPU)")

    @pytest.mark.p0
    def test_verify_emmc(self, bf3):
        """BFB-006: Verify eMMC is accessible."""
        _require_install()
        result = bf3.execute("lsblk /dev/mmcblk0")
        assert result.rc == 0, "eMMC not found"

    @pytest.mark.p1
    def test_verify_doca_runtime(self, bf3):
        """BFB-007: Verify DOCA runtime installed."""
        _require_install()
        version = bf3.get_doca_version()
        assert version != "unknown", "DOCA not installed"

    @pytest.mark.p1
    def test_verify_crypto(self, bf3):
        """BFB-009: Verify hardware crypto offload status."""
        _require_install()
        status = bf3.get_crypto_status()
        assert status, (
            "Could not query crypto status "
            "(mlxconfig/devlink not available)"
        )
        logger.info(f"Crypto status: {status}")
        if bf3.is_crypto_enabled():
            logger.info("Hardware crypto: ENABLED")
        else:
            pytest.xfail("Hardware crypto not enabled")

    @pytest.mark.p1
    def test_verify_services(self, bf3):
        """BFB-010: Verify critical services running."""
        _require_install()
        services = ["networking", "ssh", "mlx_ifc",
                     "openvswitch-switch"]
        for svc in services:
            result = bf3.execute(
                f"systemctl is-active {svc} 2>/dev/null"
            )
            if result.stdout.strip() != "active":
                pytest.xfail(f"Service {svc} not active")
