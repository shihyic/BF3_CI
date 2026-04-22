# tests/functional/test_storage.py
# Port of old_test/print-partition.sh — storage/partition verification.
# Verifies root filesystem, partition table, eMMC device presence,
# and basic disk health on BF3 DPU ARM.

import logging
import re

import pytest

pytestmark = [pytest.mark.functional]

logger = logging.getLogger(__name__)


class TestStorage:
    """Storage and partition verification on BF3 DPU ARM.

    Port of old_test/print-partition.sh, extended to cover
    eMMC presence, filesystem health, and disk I/O readability.
    """

    @pytest.mark.p0
    def test_root_filesystem_mounted(self, bf3):
        """STG-001: Root filesystem is mounted.

        Direct port of print-partition.sh root detection:
        mount | awk '/ \\/ / { print $1 }'
        """
        r = bf3.execute("mount | awk '/ \\/ / { print $1 }'")
        assert r.rc == 0, "mount command failed"
        root_dev = r.stdout.strip()
        assert root_dev, "No root filesystem found in mount output"

        logger.info(f"Root device: {root_dev}")

        if root_dev == "rootfs":
            logger.info("Running from initramfs")
        else:
            logger.info("Running from disk root filesystem")

    @pytest.mark.p0
    def test_partition_detected(self, bf3):
        """STG-002: At least one disk partition exists.

        Direct port of print-partition.sh partition detection:
        grep -v pmem0 /proc/partitions | tail -1 | awk '{print $4}'
        """
        r = bf3.execute(
            "grep -v pmem0 /proc/partitions | "
            "tail -1 | awk '{print $4}'")
        assert r.rc == 0, "Cannot read /proc/partitions"
        part = r.stdout.strip()
        assert part, "No partition found in /proc/partitions"

        logger.info(f"Last partition: {part}")

        r = bf3.execute("cat /proc/partitions")
        assert r.rc == 0
        lines = [
            l for l in r.stdout.splitlines()[2:]
            if l.strip() and "pmem0" not in l
        ]
        logger.info(f"Partitions (excluding pmem0): {len(lines)}")
        for line in lines:
            logger.info(f"  {line.strip()}")

    @pytest.mark.p0
    def test_print_partition(self, bf3):
        """STG-003: Full print-partition.sh output.

        Combined output matching the original script: root_dev + last partition.
        """
        r = bf3.execute("mount | awk '/ \\/ / { print $1 }'")
        root_dev = r.stdout.strip() if r.rc == 0 else "unknown"

        r = bf3.execute(
            "grep -v pmem0 /proc/partitions | "
            "tail -1 | awk '{print $4}'")
        part = r.stdout.strip() if r.rc == 0 else "unknown"

        logger.info(f"print-partition output: {root_dev} {part}")
        assert root_dev != "unknown", "Cannot determine root device"
        assert part != "unknown", "Cannot determine partition"

    @pytest.mark.p0
    def test_emmc_device_present(self, bf3):
        """STG-004: eMMC block device exists on BF3."""
        r = bf3.execute("ls /dev/mmcblk0 2>/dev/null")
        if r.rc != 0:
            r = bf3.execute("lsblk -d -o NAME,TYPE 2>/dev/null")
            logger.info(f"Block devices:\n{r.stdout}")
            pytest.skip("No eMMC device (/dev/mmcblk0) found")

        logger.info("eMMC device /dev/mmcblk0 present")

        r = bf3.execute(
            "cat /sys/block/mmcblk0/device/name 2>/dev/null")
        if r.rc == 0 and r.stdout.strip():
            logger.info(f"eMMC name: {r.stdout.strip()}")

        r = bf3.execute(
            "cat /sys/block/mmcblk0/size 2>/dev/null")
        if r.rc == 0 and r.stdout.strip():
            sectors = int(r.stdout.strip())
            size_gb = (sectors * 512) / (1024 ** 3)
            logger.info(f"eMMC size: {size_gb:.1f} GB "
                        f"({sectors} sectors)")

    @pytest.mark.p1
    def test_root_filesystem_writable(self, bf3):
        """STG-005: Root filesystem is writable."""
        r = bf3.execute(
            "tmpf=$(mktemp /tmp/stg_test_XXXXXX) && "
            "echo ok > $tmpf && cat $tmpf && rm -f $tmpf")
        assert r.rc == 0, "Cannot write to filesystem"
        assert "ok" in r.stdout, (
            f"Write/read-back failed: {r.stdout}")
        logger.info("Root filesystem is writable")

    @pytest.mark.p1
    def test_disk_space_available(self, bf3):
        """STG-006: Root filesystem has free space."""
        r = bf3.execute("df -h / | tail -1")
        assert r.rc == 0, "df command failed"
        logger.info(f"Root disk usage: {r.stdout.strip()}")

        m = re.search(r'(\d+)%', r.stdout)
        if m:
            usage_pct = int(m.group(1))
            logger.info(f"Disk usage: {usage_pct}%")
            if usage_pct >= 95:
                logger.warning(
                    f"Disk nearly full: {usage_pct}% used")
            assert usage_pct < 100, (
                f"Root filesystem is 100% full")

    @pytest.mark.p1
    def test_emmc_health(self, bf3):
        """STG-007: eMMC health/life indicators (if available)."""
        r = bf3.execute("ls /dev/mmcblk0 2>/dev/null")
        if r.rc != 0:
            pytest.skip("No eMMC device")

        health_paths = [
            ("/sys/block/mmcblk0/device/life_time",
             "Device life time estimate"),
            ("/sys/block/mmcblk0/device/pre_eol_info",
             "Pre-EOL info"),
            ("/sys/block/mmcblk0/device/csd",
             "CSD register"),
            ("/sys/block/mmcblk0/device/fwrev",
             "Firmware revision"),
        ]

        for path, desc in health_paths:
            r = bf3.execute(f"cat {path} 2>/dev/null")
            if r.rc == 0 and r.stdout.strip():
                logger.info(f"{desc}: {r.stdout.strip()}")
            else:
                logger.info(f"{desc}: not available")

    @pytest.mark.p2
    def test_lsblk_output(self, bf3):
        """STG-008: Full block device listing for diagnostics."""
        r = bf3.execute(
            "lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE "
            "2>/dev/null")
        if r.rc != 0:
            r = bf3.execute("cat /proc/partitions")

        assert r.rc == 0, "Cannot list block devices"
        logger.info(f"Block devices:\n{r.stdout.strip()}")

        lines = r.stdout.strip().splitlines()
        assert len(lines) > 1, "No block devices found"
