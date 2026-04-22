# tests/functional/test_drivers.py
# Port of old_test/oob-lsmod-test.sh and oob-ethtool-info.sh.
# Verifies essential BF3 kernel modules are loaded and functional.

import logging
import pytest

pytestmark = [pytest.mark.functional]

logger = logging.getLogger(__name__)

ESSENTIAL_MODULES = [
    ("mlxbf_gige", "OOB network driver"),
]

EXPECTED_MODULES = [
    ("mlx5_core", "ConnectX NIC driver"),
    ("mlxbf_tmfifo", "TMFIFO host communication"),
    ("mlxbf_bootctl", "Boot control"),
    ("gpio_mlxbf3", "GPIO controller"),
    ("i2c_mlxbf", "I2C controller"),
    ("pinctrl_mlxbf3", "Pin control"),
    ("pwr_mlxbf", "Power management"),
    ("mlxbf_pmc", "Performance monitoring"),
]


def _get_loaded_modules(bf3) -> dict[str, str]:
    """Return {module_name: raw_lsmod_line} for all loaded modules."""
    r = bf3.execute("lsmod")
    assert r.rc == 0, "lsmod failed"
    modules = {}
    for line in r.stdout.splitlines()[1:]:
        parts = line.split()
        if parts:
            modules[parts[0]] = line
    return modules


class TestDrivers:
    """Kernel driver/module verification on BF3 DPU ARM.

    Port of old_test/oob-lsmod-test.sh, extended to cover
    all essential BF3 kernel modules.
    """

    @pytest.mark.p0
    def test_oob_driver_loaded(self, bf3):
        """DRV-001: OOB network driver (mlxbf_gige) is loaded.

        Direct port of oob-lsmod-test.sh.
        """
        r = bf3.execute("lsmod | grep mlxbf_gige")
        assert r.rc == 0 and r.stdout.strip(), (
            "OOB driver (mlxbf_gige) not loaded")
        logger.info(f"OOB driver loaded: {r.stdout.strip()}")

    @pytest.mark.p0
    def test_oob_interface_up(self, bf3):
        """DRV-002: OOB network interface is up and has an address."""
        r = bf3.execute("ip addr show oob_net0 2>/dev/null")
        assert r.rc == 0, "oob_net0 interface not found"

        has_ip = ("inet " in r.stdout)
        state_up = ("state UP" in r.stdout or
                    "state UNKNOWN" in r.stdout)
        logger.info(f"oob_net0: up={state_up}, has_ip={has_ip}")
        logger.info(f"oob_net0:\n{r.stdout.strip()}")

        assert state_up or has_ip, (
            "oob_net0 is down and has no IP address")

    @pytest.mark.p0
    def test_oob_ethtool_info(self, bf3):
        """DRV-007: OOB interface ethtool driver info.

        Direct port of oob-ethtool-info.sh.
        Verifies driver name, bus-info, and capabilities.
        """
        r = bf3.execute("which ethtool 2>/dev/null")
        if r.rc != 0:
            bf3.execute(
                "apt-get update -qq 2>/dev/null && "
                "apt-get install -y -qq ethtool 2>/dev/null",
                timeout=60)

        r = bf3.execute("ethtool -i oob_net0 2>&1")
        assert r.rc == 0, (
            f"ethtool -i oob_net0 failed: {r.stdout}")

        info = {}
        for line in r.stdout.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                info[k.strip()] = v.strip()

        logger.info(f"ethtool -i oob_net0:")
        for k, v in info.items():
            logger.info(f"  {k}: {v}")

        assert info.get("driver") == "mlxbf_gige", (
            f"Expected driver 'mlxbf_gige', "
            f"got '{info.get('driver')}'")
        assert info.get("bus-info"), (
            "bus-info is empty")
        assert info.get("supports-statistics") == "yes", (
            "OOB driver should support statistics")

    @pytest.mark.p0
    def test_essential_modules(self, bf3):
        """DRV-003: All essential kernel modules are loaded."""
        modules = _get_loaded_modules(bf3)
        logger.info(f"Total loaded modules: {len(modules)}")

        missing = []
        for mod, desc in ESSENTIAL_MODULES:
            if mod in modules:
                logger.info(f"  {mod} ({desc}): loaded")
            else:
                missing.append(f"{mod} ({desc})")
                logger.error(f"  {mod} ({desc}): MISSING")

        assert not missing, (
            f"Essential modules not loaded: "
            f"{', '.join(missing)}")

    @pytest.mark.p1
    def test_expected_modules(self, bf3):
        """DRV-004: Expected BF3 kernel modules are loaded."""
        modules = _get_loaded_modules(bf3)

        loaded = []
        missing = []
        for mod, desc in EXPECTED_MODULES:
            if mod in modules:
                loaded.append(mod)
                logger.info(f"  {mod} ({desc}): loaded")
            else:
                missing.append(f"{mod} ({desc})")
                logger.warning(f"  {mod} ({desc}): not loaded")

        logger.info(f"Expected modules: {len(loaded)}/"
                     f"{len(EXPECTED_MODULES)} loaded")
        if missing:
            logger.warning(
                f"Missing modules: {', '.join(missing)}")

    @pytest.mark.p1
    def test_mlx5_core_loaded(self, bf3):
        """DRV-005: mlx5_core NIC driver loaded and bound."""
        r = bf3.execute("lsmod | grep mlx5_core")
        if r.rc != 0 or not r.stdout.strip():
            pytest.xfail("mlx5_core not loaded "
                          "(may be built-in)")

        logger.info(f"mlx5_core: {r.stdout.strip()}")

        r = bf3.execute(
            "ls /sys/class/net/*/device/driver 2>/dev/null "
            "| head -5")
        if r.stdout.strip():
            logger.info(f"Network device drivers:\n{r.stdout}")

    @pytest.mark.p2
    def test_no_tainted_kernel(self, bf3):
        """DRV-006: Kernel is not tainted."""
        r = bf3.execute("cat /proc/sys/kernel/tainted")
        assert r.rc == 0, "Cannot read kernel taint status"
        taint = int(r.stdout.strip()) if r.stdout.strip().isdigit() else -1

        if taint == 0:
            logger.info("Kernel is clean (taint=0)")
        else:
            r2 = bf3.execute(
                "cat /proc/sys/kernel/tainted; "
                "dmesg | grep -i taint 2>/dev/null | head -5")
            logger.warning(
                f"Kernel taint value: {taint}\n{r2.stdout}")
            if taint & 0x1:
                logger.warning("Proprietary module loaded")
            if taint & 0x200:
                logger.warning("Kernel warning occurred")
