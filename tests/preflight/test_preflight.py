# tests/preflight/test_preflight.py

import pytest

pytestmark = [pytest.mark.preflight, pytest.mark.p0]


class TestPreflight:
    """Pre-flight connectivity checks for BF3."""

    def test_host_reachable(self, host):
        """PF-001: Host server is reachable."""
        assert host.is_alive()

    def test_bmc_redfish_reachable(self, bmc):
        """PF-002: BMC Redfish is responding."""
        assert bmc.is_alive()

    def test_bmc_ssh_reachable(self, bmc):
        """PF-003: BMC SSH is accessible."""
        result = bmc.ssh.execute("hostname")
        assert result.rc == 0
        assert "dpu-bmc" in result.stdout

    def test_rshim_available(self, rshim):
        """PF-004: RShim device available."""
        assert rshim.is_available(), (
            f"RShim not found via {rshim.source}"
        )

    def test_bf3_pcie_visible(self, host):
        """PF-005: BF3 PCIe device visible on host."""
        result = host.execute(
            "lspci | grep -i 'Mellanox.*BlueField-3'"
        )
        assert result.rc == 0, "BF3 not found in lspci"

    def test_bf3_arm_reachable(self, bf3):
        """PF-006: BF3 ARM OS is reachable via SSH."""
        assert bf3.is_alive()

    def test_bf3_is_bluefield3(self, bf3):
        """PF-007: Verify device is actually BF3."""
        result = bf3.execute(
            "cat /sys/firmware/acpi/tables/SSDT* 2>/dev/null "
            "| strings | grep -i 'BlueField-3' || "
            "mlxfwmanager --query 2>/dev/null | "
            "grep -i 'BF3\\|BlueField-3'"
        )
        assert result.rc == 0, "Device is not BF3"

    def test_bmc_rshim_service(self, bmc):
        """PF-008: BMC rshim.service exists."""
        result = bmc.ssh.execute(
            "systemctl list-unit-files | grep rshim"
        )
        assert result.rc == 0
