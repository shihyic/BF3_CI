# tests/functional/test_network.py

import pytest

pytestmark = [pytest.mark.functional]


class TestNetwork:
    """BF3 network functionality tests."""

    @pytest.mark.p0
    def test_tmfifo_connectivity(self, bf3):
        """FN-001: ARM tmfifo_net0 interface up."""
        result = bf3.execute(
            "ip addr show tmfifo_net0 | grep 'state UP'"
        )
        assert result.rc == 0

    @pytest.mark.p0
    def test_oob_network(self, bf3):
        """FN-002: OOB management network up."""
        result = bf3.execute(
            "ip addr show oob_net0 | grep 'inet '"
        )
        assert result.rc == 0

    @pytest.mark.p0
    def test_data_port_p0(self, bf3):
        """FN-003a: Data port p0 exists."""
        result = bf3.execute("ip link show p0")
        assert result.rc == 0

    @pytest.mark.p0
    def test_data_port_p1(self, bf3):
        """FN-003b: Data port p1 exists."""
        result = bf3.execute("ip link show p1")
        assert result.rc == 0

    @pytest.mark.p1
    def test_pcie_link_speed(self, bf3):
        """FN-004: PCIe link speed is Gen5."""
        result = bf3.execute(
            "mlxfwmanager --query 2>/dev/null | "
            "grep -i 'link speed'"
        )
        # BF3 should be PCIe Gen5
        if result.rc == 0:
            assert "Gen5" in result.stdout or \
                   "32GT/s" in result.stdout

    @pytest.mark.p1
    def test_port_speed(self, bf3):
        """FN-005: Port speed is 200GbE or higher."""
        result = bf3.execute(
            "ethtool p0 2>/dev/null | grep Speed"
        )
        if result.rc == 0 and "Unknown" not in result.stdout:
            speed = result.stdout.strip()
            assert "200000" in speed or "400000" in speed, (
                f"Unexpected port speed: {speed}"
            )
