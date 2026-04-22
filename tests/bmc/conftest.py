# tests/bmc/conftest.py

import pytest
import logging

logger = logging.getLogger(__name__)


@pytest.fixture
def clean_sel(bmc):
    """Clear SEL before, collect after."""
    bmc.clear_sel()
    yield
    entries = bmc.get_sel_entries()
    if entries:
        logger.info(f"SEL entries after test: {len(entries)}")


@pytest.fixture
def rshim_enabled(bmc):
    """Ensure BMC RShim enabled, restore original state."""
    original = bmc.get_rshim_status()
    if not original:
        bmc.enable_rshim()
    yield
    if not original:
        bmc.disable_rshim()


@pytest.fixture
def rshim_disabled(bmc):
    """Ensure BMC RShim disabled, restore original state."""
    original = bmc.get_rshim_status()
    if original:
        bmc.disable_rshim()
    yield
    if original:
        bmc.enable_rshim()


@pytest.fixture
def bmc_journal_snapshot(bmc):
    """Capture journal before/after test."""
    bmc.ssh.execute(
        "journalctl --cursor-file=/tmp/test_cursor -n0"
    )
    yield
    result = bmc.ssh.execute(
        "journalctl --after-cursor="
        "$(cat /tmp/test_cursor) --no-pager"
    )
    if "error" in result.stdout.lower():
        logger.warning(
            f"Errors in BMC journal:\n{result.stdout}"
        )
