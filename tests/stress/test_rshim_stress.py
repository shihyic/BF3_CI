# tests/stress/test_rshim_stress.py

import pytest
import time
import logging

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.stress, pytest.mark.p2,
              pytest.mark.slow]


class TestRShimStress:
    """RShim enable/disable stress ? with BF3 bug detection."""

    @pytest.mark.timeout(40)
    @pytest.mark.parametrize("iteration", range(100))
    def test_rshim_enable_disable(self, bmc, iteration):
        """ST-004: RShim cycling with duration check."""
        logger.info(f"RShim stress iteration: {iteration}")

        start = time.time()

        # Enable
        assert bmc.enable_rshim(timeout=30), (
            f"Enable failed at iteration {iteration}"
        )
        time.sleep(5)

        # Disable
        assert bmc.disable_rshim(timeout=30), (
            f"Disable failed at iteration {iteration}"
        )

        duration = time.time() - start
        assert duration < 20, (
            f"Iteration {iteration}: {duration:.0f}s "
            f"(>20s = possible rshim SIGTERM timeout bug)"
        )

        # Verify no multiple rshim processes
        result = bmc.ssh.execute("pidof rshim | wc -w")
        pid_count = int(result.stdout.strip() or "0")
        assert pid_count <= 1, (
            f"Multiple rshim processes at iteration "
            f"{iteration}: {pid_count}"
        )

        time.sleep(2)
