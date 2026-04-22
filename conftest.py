# conftest.py

import pytest
import yaml
import logging

logger = logging.getLogger(__name__)


def pytest_addoption(parser):
    """BF3 CI custom CLI options."""
    parser.addoption("--testbed", default="config/testbed.yaml",
                     help="Testbed configuration YAML")
    parser.addoption("--bfb", default=None,
                     help="Path to BFB file")
    parser.addoption("--bmc-fw", default=None,
                     help="Path to BMC firmware image")
    parser.addoption("--nic-fw", default=None,
                     help="Path to NIC firmware image")
    parser.addoption("--uefi-capsule", default=None,
                     help="Path to UEFI capsule file")
    parser.addoption("--skip-install", action="store_true",
                     default=False,
                     help="Skip BFB installation")
    parser.addoption("--rshim-mode",
                     choices=["host", "bmc", "auto"],
                     default="auto",
                     help="RShim mode: host, bmc, or auto")
    parser.addoption("--recovery-mode",
                     choices=["auto", "manual", "skip"],
                     default="auto",
                     help="Device recovery mode on failure")
    parser.addoption("--stress-count", type=int, default=100,
                     help="Iteration count for stress tests")
    parser.addoption("--bf-cfg", default=None,
                     help="Path to bf.cfg for BFB install")


@pytest.fixture(scope="session")
def testbed_config(request):
    """Load testbed configuration."""
    config_path = request.config.getoption("--testbed")
    with open(config_path) as f:
        config = yaml.safe_load(f)
    logger.info(f"Loaded testbed: {config['testbed']['name']}")
    return config


TIMEOUT_DEFAULTS = {
    "ssh_connect": 30,
    "boot_wait": 600,
    "bfb_install": 2400,
    "bfb_complete": 2400,
    "rshim_enable": 120,
    "rshim_disable": 60,
    "bmc_fw_update": 900,
    "bmc_reboot": 300,
    "uefi_capsule": 600,
    "power_cycle": 600,
    "stress_reboot": 600,
    "default": 300,
}


@pytest.fixture(scope="session")
def timeouts(testbed_config):
    """Testbed-aware timeouts merged with built-in defaults."""
    cfg = testbed_config.get("testbed", {}).get("timeouts", {})
    merged = {**TIMEOUT_DEFAULTS, **cfg}
    logger.info(f"Timeouts: {merged}")
    return merged


@pytest.fixture(scope="session")
def bfb_path(request):
    return request.config.getoption("--bfb")


@pytest.fixture(scope="session")
def bmc_fw_path(request):
    return request.config.getoption("--bmc-fw")


@pytest.fixture(scope="session")
def nic_fw_path(request):
    return request.config.getoption("--nic-fw")


@pytest.fixture(scope="session")
def uefi_capsule_path(request):
    return request.config.getoption("--uefi-capsule")


@pytest.fixture(scope="session")
def rshim_mode(request):
    return request.config.getoption("--rshim-mode")


@pytest.fixture(scope="session")
def bf_cfg_path(request):
    return request.config.getoption("--bf-cfg")


@pytest.fixture(scope="session")
def stress_count(request):
    return request.config.getoption("--stress-count")


