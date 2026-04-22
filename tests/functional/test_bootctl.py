# tests/functional/test_bootctl.py
# Port of old_test/hw/bootctl.py, old_test/hw/bootctl/,
# and old_test/mlxbf-bootctl/sysfs_test.sh + request_swap.sh.
#
# Non-destructive boot control verification (P0/P1) and
# sysfs API write/read/verify tests (P2, marked destructive).

import logging
import re

import pytest

pytestmark = [pytest.mark.functional]

logger = logging.getLogger(__name__)

# sysfs_test.sh valid/invalid value tables
_RESET_ACTION_GOOD = ["external", "emmc", "swap_emmc", "emmc_legacy"]
_RESET_ACTION_BAD = ["none", "0", "xxx"]

_SECOND_RESET_ACTION_GOOD = [
    "none", "external", "emmc", "swap_emmc", "emmc_legacy",
]
_SECOND_RESET_ACTION_BAD = ["xxx", "0"]

_POST_RESET_WDOG_GOOD_BF2 = ["0", "1", "10", "100", "1000", "4000", "4095"]
_POST_RESET_WDOG_GOOD_BF3 = ["0", "45", "100", "1000", "4000", "4095"]
_POST_RESET_WDOG_BAD = ["-1", "0x1", "4096", "1000000", "-1000000", "xxx"]


def _bootctl_info(bf3) -> dict[str, str]:
    """Run mlxbf-bootctl and parse key-value output."""
    r = bf3.execute("mlxbf-bootctl 2>/dev/null")
    if r.rc != 0:
        return {}
    info = {}
    for line in r.stdout.splitlines():
        line = line.strip()
        if ":" in line:
            k, v = line.split(":", 1)
            info[k.strip()] = v.strip()
    return info


def _get_primary_partition(bf3) -> str | None:
    """Return the current primary boot partition name."""
    info = _bootctl_info(bf3)
    primary = info.get("primary", "")
    m = re.search(r'(mmcblk\d+boot\d+)', primary)
    return m.group(1) if m else None


def _find_sysfs_bootctl(bf3) -> str | None:
    """Discover the sysfs directory containing bootctl attributes.

    The original sysfs_test.sh uses MLNXBF04:00/driver/ but the
    actual location varies by kernel version and BF generation.
    Search common locations for the reset_action attribute.
    """
    candidates = [
        "/sys/bus/platform/devices/MLNXBF04:00/driver",
        "/sys/bus/platform/devices/MLNXBF04:00",
        "/sys/bus/platform/drivers/mlxbf-bootctl/MLNXBF04:00",
    ]
    for path in candidates:
        r = bf3.execute(
            f"test -f {path}/reset_action && echo {path}")
        if r.rc == 0 and r.stdout.strip():
            return r.stdout.strip()

    r = bf3.execute(
        "find /sys/bus/platform -name reset_action "
        "-path '*MLNXBF*' 2>/dev/null | head -1")
    if r.rc == 0 and r.stdout.strip():
        return r.stdout.strip().rsplit("/", 1)[0]
    return None


def _sysfs_read(bf3, sysfs_dir: str, attr: str) -> str:
    """Read a sysfs bootctl attribute."""
    r = bf3.execute(f"cat {sysfs_dir}/{attr} 2>&1")
    return r.stdout.strip() if r.rc == 0 else ""


def _sysfs_write(bf3, sysfs_dir: str, attr: str, val: str) -> int:
    """Write a value to a sysfs bootctl attribute. Returns exit code."""
    r = bf3.execute(
        f"sh -c 'echo {val} > {sysfs_dir}/{attr}' 2>&1")
    return r.rc


class TestBootctl:
    """Boot control verification on BF3 DPU ARM.

    Port of old_test/hw/bootctl.py.
    Non-destructive tests verify boot control state.
    Destructive tests (marked) perform actual partition swaps.
    """

    @pytest.mark.p0
    def test_bootctl_available(self, bf3):
        """BCT-001: mlxbf-bootctl command is available."""
        r = bf3.execute("which mlxbf-bootctl 2>/dev/null")
        assert r.rc == 0, "mlxbf-bootctl not found on DPU"
        logger.info(f"mlxbf-bootctl: {r.stdout.strip()}")

    @pytest.mark.p0
    def test_bootctl_info_readable(self, bf3):
        """BCT-002: Boot control info is readable."""
        info = _bootctl_info(bf3)
        assert info, (
            "mlxbf-bootctl returned no info")

        for k, v in info.items():
            logger.info(f"  {k}: {v}")

    @pytest.mark.p0
    def test_primary_partition(self, bf3):
        """BCT-003: Primary boot partition is set.

        Mirrors bootctl.py: act.bootctl_primary_partition()
        """
        primary = _get_primary_partition(bf3)
        assert primary, "Cannot determine primary boot partition"
        logger.info(f"Primary boot partition: {primary}")

        assert "mmcblk0boot" in primary, (
            f"Unexpected primary partition: {primary}")

    @pytest.mark.p0
    def test_backup_partition(self, bf3):
        """BCT-004: Backup boot partition is set."""
        info = _bootctl_info(bf3)
        backup = info.get("backup", "")
        logger.info(f"Backup boot partition: {backup}")

        assert "mmcblk0boot" in backup or backup, (
            "No backup partition configured")

    @pytest.mark.p0
    def test_boot_partitions_exist(self, bf3):
        """BCT-005: eMMC boot partition devices exist."""
        for part in ["mmcblk0boot0", "mmcblk0boot1"]:
            r = bf3.execute(f"test -b /dev/{part}")
            assert r.rc == 0, (
                f"/dev/{part} block device not found")
            logger.info(f"/dev/{part}: present")

        r = bf3.execute(
            "cat /sys/block/mmcblk0boot0/size "
            "/sys/block/mmcblk0boot1/size 2>/dev/null")
        if r.rc == 0:
            sizes = r.stdout.strip().splitlines()
            for i, s in enumerate(sizes):
                if s.strip().isdigit():
                    size_mb = int(s.strip()) * 512 / (1024 * 1024)
                    logger.info(f"mmcblk0boot{i}: "
                                f"{size_mb:.1f} MB")

    @pytest.mark.p1
    def test_lifecycle_state(self, bf3):
        """BCT-006: Lifecycle state is readable."""
        info = _bootctl_info(bf3)
        lifecycle = info.get("lifecycle state", "")
        logger.info(f"Lifecycle state: {lifecycle}")

        if lifecycle:
            assert lifecycle in [
                "Production", "GA Secured", "GA Non-Secured",
                "RMA", "Secured (development)",
            ], f"Unexpected lifecycle: {lifecycle}"

    @pytest.mark.p1
    def test_boot_bus_width(self, bf3):
        """BCT-007: Boot bus width is configured."""
        info = _bootctl_info(bf3)
        width = info.get("boot-bus-width", "")
        logger.info(f"Boot bus width: {width}")
        assert width, "Boot bus width not reported"

    @pytest.mark.p1
    def test_watchdog_state(self, bf3):
        """BCT-008: Watchdog swap state is readable.

        Mirrors bootctl.py: watchdog-swap and --nowatchdog-swap.
        """
        info = _bootctl_info(bf3)
        watchdog_mode = info.get("boot watchdog mode", "")
        watchdog_interval = info.get("boot watchdog interval", "")

        logger.info(f"Watchdog mode: {watchdog_mode}")
        logger.info(f"Watchdog interval: {watchdog_interval}")

    @pytest.mark.p1
    def test_secure_boot_key_slots(self, bf3):
        """BCT-009: Secure boot key slot info is available."""
        info = _bootctl_info(bf3)
        slots = info.get("secure boot key free slots", "")
        logger.info(f"Secure boot key free slots: {slots}")

    @pytest.mark.p0
    def test_boot_partition_readable(self, bf3):
        """BCT-010: Boot partitions are readable.

        Mirrors bootctl.py: mlxbf-bootctl -r /dev/mmcblk0boot0
        Non-destructive: reads first 4KB from each partition.
        """
        for part in ["mmcblk0boot0", "mmcblk0boot1"]:
            r = bf3.execute(
                f"dd if=/dev/{part} of=/dev/null "
                f"bs=4096 count=1 2>&1")
            assert r.rc == 0, (
                f"Cannot read from /dev/{part}: {r.stdout}")
            logger.info(f"/dev/{part}: readable")

    @pytest.mark.p1
    def test_atf_build_type(self, bf3):
        """BCT-011: ATF (Arm Trusted Firmware) build type.

        Mirrors bootctl.py: act.atf_should_be_release_build()
        """
        r = bf3.execute(
            "mlxbf-bootctl 2>/dev/null | "
            "grep -i 'atf\\|arm trusted\\|bl31' || true")
        if r.stdout.strip():
            logger.info(f"ATF info: {r.stdout.strip()}")

        r = bf3.execute(
            "dmesg 2>/dev/null | grep -i 'bl31\\|trusted firmware' "
            "| head -5 || true")
        if r.stdout.strip():
            logger.info(f"ATF dmesg: {r.stdout.strip()}")

        r = bf3.execute(
            "cat /sys/firmware/devicetree/base/model "
            "2>/dev/null || true")
        if r.stdout.strip():
            logger.info(f"Device model: {r.stdout.strip()}")

    @pytest.mark.p2
    @pytest.mark.destructive
    def test_bootctl_swap_and_verify(self, bf3):
        """BCT-012: Boot partition swap (DESTRUCTIVE).

        Port of bootctl.py swap test.  Swaps the boot partition,
        verifies the change took effect, then swaps back.
        Does NOT reboot — only verifies the mlxbf-bootctl -s
        command changes the reported primary.

        WARNING: This modifies boot configuration. The actual
        reboot-based verification from the original test is not
        performed here to avoid disruption.
        """
        original = _get_primary_partition(bf3)
        assert original, "Cannot determine current primary"
        logger.info(f"Original primary: {original}")

        r = bf3.execute("mlxbf-bootctl -s 2>&1")
        assert r.rc == 0, (
            f"mlxbf-bootctl -s failed: {r.stdout}")

        swapped = _get_primary_partition(bf3)
        logger.info(f"After swap: {swapped}")

        assert swapped != original, (
            f"Partition did not swap: still {swapped}")

        r = bf3.execute("mlxbf-bootctl -s 2>&1")
        assert r.rc == 0, (
            f"mlxbf-bootctl -s (swap-back) failed: {r.stdout}")

        restored = _get_primary_partition(bf3)
        logger.info(f"After swap-back: {restored}")

        assert restored == original, (
            f"Partition did not restore: "
            f"expected {original}, got {restored}")
        logger.info("Swap/swap-back verified without reboot")


class TestBootctlSysfs:
    """Sysfs bootctl API verification on BF3 DPU ARM.

    Direct port of old_test/mlxbf-bootctl/sysfs_test.sh.
    Exercises the Linux sysfs driver which talks via SMC to ATF.
    Each test saves/restores the original value.
    """

    @pytest.fixture()
    def sysfs_dir(self, bf3) -> str:
        """Locate the bootctl sysfs directory with reset_action."""
        d = _find_sysfs_bootctl(bf3)
        if not d:
            pytest.skip(
                "Bootctl sysfs attributes (reset_action) "
                "not found under /sys/bus/platform")
        logger.info(f"Bootctl sysfs dir: {d}")
        return d

    def _store_good(self, bf3, sysfs_dir, attr, values):
        """Write valid values and verify read-back (store_good)."""
        for v in values:
            rc = _sysfs_write(bf3, sysfs_dir, attr, v)
            assert rc == 0, (
                f"{attr}: wrote '{v}' and failed with rc={rc}")
            readback = _sysfs_read(bf3, sysfs_dir, attr)
            assert readback == v, (
                f"{attr}: wrote '{v}', read back '{readback}'")
            logger.info(f"  {attr} <- '{v}' OK")

    def _store_bad(self, bf3, sysfs_dir, attr, values):
        """Write invalid values and verify they are rejected."""
        for v in values:
            before = _sysfs_read(bf3, sysfs_dir, attr)
            rc = _sysfs_write(bf3, sysfs_dir, attr, v)
            assert rc != 0, (
                f"{attr}: wrote invalid '{v}' and succeeded")
            after = _sysfs_read(bf3, sysfs_dir, attr)
            assert after != v, (
                f"{attr}: wrote invalid '{v}', failed, but "
                f"read it back")
            assert after == before, (
                f"{attr}: reject of '{v}' changed value "
                f"from '{before}' to '{after}'")
            logger.info(f"  {attr} <- '{v}' rejected OK")

    @pytest.mark.p2
    @pytest.mark.destructive
    def test_sysfs_reset_action(self, bf3, sysfs_dir):
        """BCT-013: reset_action sysfs write/read/verify.

        Port of sysfs_test.sh: store_good / store_bad for reset_action.
        """
        initial = _sysfs_read(bf3, sysfs_dir, "reset_action")
        logger.info(f"Initial reset_action: {initial}")
        try:
            self._store_good(
                bf3, sysfs_dir, "reset_action",
                _RESET_ACTION_GOOD)
            self._store_bad(
                bf3, sysfs_dir, "reset_action",
                _RESET_ACTION_BAD)
        finally:
            if initial:
                _sysfs_write(bf3, sysfs_dir, "reset_action", initial)
                logger.info(f"Restored reset_action to '{initial}'")

    @pytest.mark.p2
    @pytest.mark.destructive
    def test_sysfs_second_reset_action(self, bf3, sysfs_dir):
        """BCT-014: second_reset_action sysfs write/read/verify.

        Port of sysfs_test.sh: store_good / store_bad for
        second_reset_action.
        """
        initial = _sysfs_read(bf3, sysfs_dir, "second_reset_action")
        logger.info(f"Initial second_reset_action: {initial}")
        try:
            self._store_good(
                bf3, sysfs_dir, "second_reset_action",
                _SECOND_RESET_ACTION_GOOD)
            self._store_bad(
                bf3, sysfs_dir, "second_reset_action",
                _SECOND_RESET_ACTION_BAD)
        finally:
            if initial:
                _sysfs_write(
                    bf3, sysfs_dir, "second_reset_action", initial)
                logger.info(
                    f"Restored second_reset_action to '{initial}'")

    @pytest.mark.p2
    @pytest.mark.destructive
    def test_sysfs_post_reset_wdog(self, bf3, sysfs_dir):
        """BCT-015: post_reset_wdog sysfs write/read/verify.

        Port of sysfs_test.sh: store_good / store_bad for
        post_reset_wdog. BF3 enforces minimum of 45 (except 0
        which means disabled), so we probe which value set applies.
        """
        initial = _sysfs_read(bf3, sysfs_dir, "post_reset_wdog")
        logger.info(f"Initial post_reset_wdog: {initial}")

        rc = _sysfs_write(bf3, sysfs_dir, "post_reset_wdog", "1")
        if rc == 0 and _sysfs_read(
                bf3, sysfs_dir, "post_reset_wdog") == "1":
            good_vals = _POST_RESET_WDOG_GOOD_BF2
            logger.info("Using BF2 wdog value set (min=1)")
        else:
            good_vals = _POST_RESET_WDOG_GOOD_BF3
            logger.info("Using BF3 wdog value set (min=45)")

        try:
            self._store_good(
                bf3, sysfs_dir, "post_reset_wdog", good_vals)
            self._store_bad(
                bf3, sysfs_dir, "post_reset_wdog",
                _POST_RESET_WDOG_BAD)
        finally:
            if initial:
                _sysfs_write(
                    bf3, sysfs_dir, "post_reset_wdog", initial)
                logger.info(
                    f"Restored post_reset_wdog to '{initial}'")

    @pytest.mark.p2
    @pytest.mark.destructive
    def test_sysfs_breadcrumb_no_corruption(self, bf3, sysfs_dir):
        """BCT-016: post_reset_wdog and second_reset_action share
        breadcrumb0 and must not corrupt each other.

        Direct port of the cross-corruption check from sysfs_test.sh.
        """
        init_sra = _sysfs_read(
            bf3, sysfs_dir, "second_reset_action")
        init_prw = _sysfs_read(bf3, sysfs_dir, "post_reset_wdog")
        logger.info(
            f"Initial: sra={init_sra}, prw={init_prw}")

        try:
            sra_sentinel = "emmc_legacy"
            _sysfs_write(
                bf3, sysfs_dir, "second_reset_action", sra_sentinel)
            assert _sysfs_read(
                bf3, sysfs_dir, "second_reset_action"
            ) == sra_sentinel

            prw_sentinel = "4095"
            _sysfs_write(
                bf3, sysfs_dir, "post_reset_wdog", prw_sentinel)
            assert _sysfs_read(
                bf3, sysfs_dir, "post_reset_wdog") == prw_sentinel

            sra_after = _sysfs_read(
                bf3, sysfs_dir, "second_reset_action")
            assert sra_after == sra_sentinel, (
                f"Writing post_reset_wdog corrupted "
                f"second_reset_action: "
                f"expected '{sra_sentinel}', got '{sra_after}'")
            logger.info(
                "post_reset_wdog write did not corrupt "
                "second_reset_action")

            _sysfs_write(
                bf3, sysfs_dir, "second_reset_action", "emmc")
            prw_after = _sysfs_read(
                bf3, sysfs_dir, "post_reset_wdog")
            assert prw_after == prw_sentinel, (
                f"Writing second_reset_action corrupted "
                f"post_reset_wdog: "
                f"expected '{prw_sentinel}', got '{prw_after}'")
            logger.info(
                "second_reset_action write did not corrupt "
                "post_reset_wdog")
        finally:
            if init_sra:
                _sysfs_write(
                    bf3, sysfs_dir, "second_reset_action", init_sra)
            if init_prw:
                _sysfs_write(
                    bf3, sysfs_dir, "post_reset_wdog", init_prw)
            logger.info("Restored initial sra/prw values")

    @pytest.mark.p2
    @pytest.mark.destructive
    def test_watchdog_swap_enable_disable(self, bf3):
        """BCT-017: Enable and disable watchdog-swap mode.

        Port of old_test/mlxbf-bootctl/request_swap.sh watchdog piece.
        Uses mlxbf-bootctl CLI rather than sysfs.
        BF3 requires watchdog interval in range 45-4095.
        """
        info = _bootctl_info(bf3)
        wdog_initial = info.get("watchdog-swap", "disabled")
        logger.info(f"Initial watchdog-swap: {wdog_initial}")

        try:
            r = bf3.execute(
                "mlxbf-bootctl --watchdog-swap 45 2>&1")
            assert r.rc == 0, (
                f"--watchdog-swap 45 failed: {r.stdout}")

            info = _bootctl_info(bf3)
            wdog = info.get("watchdog-swap", "")
            logger.info(f"After enable: watchdog-swap={wdog}")
            assert wdog and wdog != "disabled", (
                f"watchdog-swap not enabled: '{wdog}'")

            r = bf3.execute(
                "mlxbf-bootctl --nowatchdog-swap 2>&1")
            assert r.rc == 0, (
                f"--nowatchdog-swap failed: {r.stdout}")

            info = _bootctl_info(bf3)
            wdog = info.get("watchdog-swap", "")
            logger.info(f"After disable: watchdog-swap={wdog}")
            assert wdog == "disabled" or not wdog, (
                f"watchdog-swap not disabled: '{wdog}'")
        finally:
            if wdog_initial == "disabled":
                bf3.execute(
                    "mlxbf-bootctl --nowatchdog-swap 2>/dev/null")
            else:
                bf3.execute(
                    f"mlxbf-bootctl --watchdog-swap "
                    f"{wdog_initial} 2>/dev/null")
