# tests/bmc/test_bmc_power.py

import pytest
import time

pytestmark = [pytest.mark.bmc, pytest.mark.destructive]


class TestBMCPower:
    """BMC host power control tests."""

    @pytest.mark.p0
    @pytest.mark.timeout(600)
    def test_host_power_cycle(self, bf3, bmc):
        """BMC-009a: Power cycle via BMC."""
        bmc.host_power_cycle()
        assert bf3.wait_for_boot(timeout=300)

    @pytest.mark.p0
    @pytest.mark.timeout(600)
    def test_host_power_off_on(self, bf3, bmc):
        """BMC-009b: Power off then on."""
        bmc.host_power_off()
        time.sleep(30)
        bmc.host_power_on()
        assert bf3.wait_for_boot(timeout=300)

    @pytest.mark.p0
    def test_get_host_state(self, bmc):
        """BMC-009c: Get host state."""
        state = bmc.get_host_state()
        assert state
        assert "CurrentHostState" in state

    @pytest.mark.p1
    def test_get_smartnic_os_state(self, bmc):
        """BMC-009d: Get SmartNIC OS state."""
        state = bmc.get_smartnic_os_state()
        assert state
        assert "OsIsRunning" in state or "Running" in state
