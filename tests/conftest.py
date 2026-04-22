# tests/conftest.py

import pytest
import logging
from bf3_ci.devices.bf3_device import BF3Device
from bf3_ci.devices.bmc_device import BMCDevice
from bf3_ci.devices.host_device import HostDevice
from bf3_ci.lib.health_check import HealthCheck

logger = logging.getLogger(__name__)


# ??? Device Fixtures ?????????????????????????????????????

@pytest.fixture(scope="session")
def bf3(testbed_config):
    """Create and connect BF3 device."""
    dut_config = testbed_config["testbed"]["dut"][0]
    device = BF3Device(dut_config)
    device.connect()
    yield device
    device.disconnect()


@pytest.fixture(scope="session")
def bmc(bf3):
    """Get BMC device."""
    return bf3.bmc


@pytest.fixture(scope="session")
def host(testbed_config):
    """Create and connect to host server."""
    host_config = testbed_config["testbed"]["dut"][0]["host"]
    device = HostDevice(host_config)
    device.connect()
    yield device
    device.disconnect()


@pytest.fixture(scope="session")
def rshim(host, bmc, rshim_mode):
    """Get appropriate RShim device based on mode.

    BF3 supports RShim via host (USB) or BMC.
    """
    from bf3_ci.devices.rshim_device import RShimDevice
    if rshim_mode == "host":
        return RShimDevice(transport=host.ssh, source="host")
    elif rshim_mode == "bmc":
        return RShimDevice(transport=bmc.ssh, source="bmc")
    else:  # auto
        host_rshim = RShimDevice(transport=host.ssh,
                                  source="host")
        if host_rshim.is_available():
            return host_rshim
        bmc_rshim = RShimDevice(transport=bmc.ssh,
                                 source="bmc")
        if bmc_rshim.is_available():
            return bmc_rshim
        pytest.fail("No RShim available on host or BMC")


@pytest.fixture(scope="session")
def health(bf3, bmc, host):
    """Health check utility."""
    return HealthCheck(bf3=bf3, bmc=bmc, host=host)


# ??? Version Snapshot ????????????????????????????????????

@pytest.fixture(scope="session")
def fw_versions(bf3, bmc):
    """Collect all firmware versions at session start."""
    versions = {
        "arm_os": bf3.get_arm_os_version(),
        "atf": bf3.get_atf_version(),
        "uefi": bf3.get_uefi_version(),
        "nic_fw": bf3.get_nic_fw_version(),
        "bmc_fw": bmc.get_firmware_version(),
        "bmc_build_id": bmc.get_build_id(),
        "cx_fw": bf3.get_cx_fw_version(),
        "doca": bf3.get_doca_version(),
    }
    logger.info(f"Firmware versions: {versions}")
    return versions


# ??? Auto-use Fixtures ???????????????????????????????????

@pytest.fixture(autouse=True)
def log_test_boundary(request):
    """Log test start/end."""
    name = request.node.name
    logger.info(f"{'='*60}")
    logger.info(f"START: {name}")
    logger.info(f"{'='*60}")
    yield
    logger.info(f"END: {name}")


@pytest.fixture(autouse=True)
def check_device_alive(request, bf3, bmc):
    """Verify device reachability before each test."""
    markers = set(request.node.keywords.keys())
    if "preflight" in markers:
        return
    if not bmc.is_alive():
        pytest.skip("BMC is not reachable")
    if "bfb" not in markers and "bmc" not in markers:
        if not bf3.is_alive():
            pytest.skip("BF3 ARM is not reachable")
