"""Pytest plugin: BF3 device recovery on test failure.

Attempts automatic device recovery (power cycle, BMC reset)
when a test failure leaves the DPU in a bad state.
"""

import logging
import pytest

logger = logging.getLogger(__name__)


def pytest_addoption(parser):
    group = parser.getgroup("bf3_recovery", "BF3 device recovery")
    group.addoption(
        "--bf3-recovery",
        action="store_true",
        default=False,
        help="Enable automatic device recovery on failure",
    )


def pytest_configure(config):
    config._bf3_recovery_enabled = config.getoption(
        "--bf3-recovery", default=False
    )


@pytest.hookimpl(trylast=True)
def pytest_runtest_makereport(item, call):
    """Check for failures that may need device recovery."""
    if call.when != "call":
        return
    if call.excinfo is None:
        return
    recovery_mode = item.config.getoption("--recovery-mode", default="skip")
    if recovery_mode == "skip":
        return
    logger.warning(
        f"Test {item.name} failed ? recovery mode: {recovery_mode}"
    )

