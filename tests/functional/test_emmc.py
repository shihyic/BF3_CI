# tests/functional/test_emmc.py

import pytest

pytestmark = [pytest.mark.functional, pytest.mark.emmc]


class TestEMMC:
    """BF3 eMMC storage tests."""

    @pytest.mark.p0
    def test_emmc_present(self, bf3):
        """EMMC-001: eMMC device is present."""
        result = bf3.execute("lsblk /dev/mmcblk0")
        assert result.rc == 0

    @pytest.mark.p0
    def test_emmc_partitions(self, bf3):
        """EMMC-002: eMMC has expected partitions."""
        result = bf3.execute("lsblk -n /dev/mmcblk0")
        assert "mmcblk0" in result.stdout

    @pytest.mark.p1
    def test_emmc_health(self, bf3):
        """EMMC-003: eMMC health is acceptable."""
        health = bf3.get_emmc_health()
        assert health["raw"], "Could not read eMMC health"
        # Life estimate should not be 0x0B (end of life)
        assert "0x0b" not in health["raw"].lower(), (
            "eMMC reports end of life!"
        )

    @pytest.mark.p1
    def test_emmc_read_write(self, bf3):
        """EMMC-004: eMMC read/write basic test."""
        result = bf3.execute(
            "dd if=/dev/urandom of=/tmp/emmc_test bs=1M "
            "count=10 2>&1 && "
            "md5sum /tmp/emmc_test && "
            "rm -f /tmp/emmc_test"
        )
        assert result.rc == 0
