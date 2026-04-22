# tests/bmc/test_bmc_rshim.py

import pytest
import time
import logging

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.bmc]


class TestBMCRShim:
    """BMC RShim tests ? BF3 specific."""

    @pytest.mark.p0
    def test_enable_rshim(self, bmc):
        """BMC-007a: Enable RShim via Redfish."""
        assert bmc.enable_rshim(timeout=60)
        assert bmc.get_rshim_status() is True

    @pytest.mark.p0
    def test_disable_rshim(self, bmc):
        """BMC-007b: Disable RShim via Redfish."""
        assert bmc.disable_rshim(timeout=60)
        assert bmc.get_rshim_status() is False

    @pytest.mark.p0
    def test_rshim_enable_disable_cycle(self, bmc):
        """BMC-007c: Enable then disable cycle."""
        assert bmc.enable_rshim(timeout=60)
        time.sleep(5)
        assert bmc.disable_rshim(timeout=60)

    @pytest.mark.p0
    def test_rshim_disable_duration(self, bmc):
        """BMC-007d: Disable completes under 20 seconds."""
        bmc.enable_rshim(timeout=60)
        time.sleep(5)

        start = time.time()
        assert bmc.disable_rshim(timeout=30)
        duration = time.time() - start

        assert duration < 20, (
            f"Disable took {duration:.0f}s (limit: 20s)"
        )

    @pytest.mark.p0
    def test_rshim_service_no_multiple_instances(
            self, bmc, bmc_journal_snapshot):
        """BMC-007e: Verify only one rshim instance runs."""
        bmc.enable_rshim(timeout=60)
        time.sleep(5)

        result = bmc.ssh.execute("pidof rshim | wc -w")
        pid_count = int(result.stdout.strip())
        assert pid_count <= 1, (
            f"Multiple rshim processes: {pid_count}"
        )

    @pytest.mark.p1
    def test_rshim_service_clean_stop(
            self, bmc, bmc_journal_snapshot):
        """BMC-007f: rshim.service stops without timeout."""
        bmc.enable_rshim(timeout=60)
        time.sleep(5)

        start = time.time()
        bmc.ssh.execute("systemctl stop rshim.service",
                        timeout=30)
        duration = time.time() - start

        # Should not require SIGKILL (90s timeout)
        assert duration < 30, (
            f"rshim stop took {duration:.0f}s "
            f"(possible SIGTERM timeout)"
        )

        # Check no timeout in journal
        result = bmc.ssh.execute(
            "journalctl -u rshim.service --since='-1min' "
            "--no-pager | grep -i 'timed out\\|SIGKILL'"
        )
        assert result.rc != 0, (
            f"rshim service had timeout: {result.stdout}"
        )

    @pytest.mark.p1
    def test_rshim_tmfifo_net0_after_enable(self, bmc):
        """BMC-007g: tmfifo_net0 appears after RShim enable."""
        bmc.disable_rshim(timeout=60)
        time.sleep(3)

        bmc.enable_rshim(timeout=60)
        time.sleep(10)

        result = bmc.ssh.execute("ip link show tmfifo_net0")
        assert result.rc == 0, (
            "tmfifo_net0 not found after RShim enable"
        )
