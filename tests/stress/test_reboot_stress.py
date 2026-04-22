# tests/stress/test_reboot_stress.py

import pytest
import logging

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.stress, pytest.mark.destructive,
              pytest.mark.slow]


class TestRebootStress:
    """Reboot stress tests."""

    @pytest.mark.timeout(600)
    @pytest.mark.parametrize("iteration", range(50))
    def test_arm_warm_reboot(self, bf3, iteration):
        """ST-002: Repeated warm reboot."""
        logger.info(f"Warm reboot iteration: {iteration}")
        bf3.warm_reboot()
        assert bf3.wait_for_boot(timeout=300), (
            f"Boot failed at iteration {iteration}"
        )

    @pytest.mark.timeout(600)
    @pytest.mark.parametrize("iteration", range(50))
    def test_bmc_reboot(self, bmc, iteration):
        """ST-003: Repeated BMC reboot."""
        logger.info(f"BMC reboot iteration: {iteration}")
        bmc.reboot()
        assert bmc.wait_for_ready(timeout=300), (
            f"BMC not ready at iteration {iteration}"
        )

    @pytest.mark.timeout(1800)
    @pytest.mark.parametrize("iteration", range(10))
    def test_bfb_reinstall(self, bf3, rshim, bfb_path,
                            iteration):
        """ST-001: Repeated BFB install."""
        if bfb_path is None:
            pytest.skip("No BFB specified")

        logger.info(f"BFB install iteration: {iteration}")
        assert rshim.push_bfb(bfb_path)
        assert rshim.wait_for_bfb_complete(timeout=900)
        assert bf3.wait_for_boot(timeout=600), (
            f"Boot failed at iteration {iteration}"
        )
