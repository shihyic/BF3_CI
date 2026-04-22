"""Pytest plugin: BF3 CI report enhancements.

Adds firmware version metadata and DUT info to test reports.
"""

import logging
import pytest

logger = logging.getLogger(__name__)


def pytest_configure(config):
    config._bf3_report_data = {}


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    logger.info("BF3 report plugin loaded")


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    report_data = getattr(config, "_bf3_report_data", {})
    if not report_data:
        return
    terminalreporter.section("BF3 DUT Information")
    for key, value in report_data.items():
        terminalreporter.line(f"  {key}: {value}")

