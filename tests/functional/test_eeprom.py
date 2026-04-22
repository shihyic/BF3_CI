# tests/functional/test_eeprom.py

import logging
import random
import time
import pytest

pytestmark = [pytest.mark.functional]

logger = logging.getLogger(__name__)

RANDOM_RW_TEST_COUNT = 16
SCRATCH_OFFSET = 0xF0
SCRATCH_LEN = 16

_eeprom = {"path": None, "size": 0, "method": None,
           "bus": None, "slave": None}


def _discover_sysfs(bf3) -> bool:
    """Find EEPROM via sysfs (kernel driver-backed)."""
    for pattern in [
        "/sys/bus/i2c/devices/*/eeprom",
        "/sys/bus/i2c/devices/*/nvmem",
    ]:
        r = bf3.execute(f"ls {pattern} 2>/dev/null")
        if r.rc == 0 and r.stdout.strip():
            for path in r.stdout.strip().splitlines():
                path = path.strip()
                sz = bf3.execute(f"wc -c < {path} 2>/dev/null")
                size = int(sz.stdout.strip()) if sz.rc == 0 else 0
                rd = bf3.execute(
                    f"dd if={path} bs=1 count=1 "
                    f"2>/dev/null | od -A x -t x1")
                if rd.rc == 0 and rd.stdout.strip():
                    _eeprom["path"] = path
                    _eeprom["size"] = size
                    _eeprom["method"] = "sysfs"
                    logger.info(
                        f"EEPROM via sysfs: {path} "
                        f"({size} bytes)")
                    return True
    return False


def _discover_i2c(bf3) -> bool:
    """Find EEPROM via raw I2C, trying multiple read modes."""
    r = bf3.execute("ls /dev/i2c-* 2>/dev/null")
    if r.rc != 0 or not r.stdout:
        return False
    buses = []
    for p in r.stdout.split():
        try:
            buses.append(int(p.rsplit("-", 1)[1]))
        except (ValueError, IndexError):
            continue
    logger.info(f"I2C buses: {buses}")

    for bus in sorted(buses):
        for slave in [0x50, 0x51, 0x52, 0x53]:
            det = bf3.execute(
                f"i2cdetect -y -r {bus} "
                f"0x{slave:02x} 0x{slave:02x} 2>/dev/null")
            if det.rc != 0 or "--" in det.stdout.split("\n")[-1]:
                continue

            # Try 1: SMBus Read Byte Data (i2cget default)
            rd = bf3.execute(
                f"i2cget -f -y {bus} 0x{slave:02x} 0x00 2>&1")
            if rd.rc == 0 and "0x" in rd.stdout:
                _eeprom["bus"] = bus
                _eeprom["slave"] = slave
                _eeprom["method"] = "i2c"
                logger.info(
                    f"EEPROM via i2c (byte-data): bus={bus} "
                    f"slave=0x{slave:02x}")
                return True

            # Try 2: SMBus Receive Byte (no register addr)
            rd = bf3.execute(
                f"i2cget -f -y {bus} 0x{slave:02x} 2>&1")
            if rd.rc == 0 and "0x" in rd.stdout:
                _eeprom["bus"] = bus
                _eeprom["slave"] = slave
                _eeprom["method"] = "i2c"
                logger.info(
                    f"EEPROM via i2c (recv-byte): bus={bus} "
                    f"slave=0x{slave:02x}")
                return True

            # Try 3: Word read mode
            rd = bf3.execute(
                f"i2cget -f -y {bus} 0x{slave:02x} 0x00 w 2>&1")
            if rd.rc == 0 and "0x" in rd.stdout:
                _eeprom["bus"] = bus
                _eeprom["slave"] = slave
                _eeprom["method"] = "i2c"
                logger.info(
                    f"EEPROM via i2c (word): bus={bus} "
                    f"slave=0x{slave:02x}")
                return True

            logger.info(
                f"bus={bus} 0x{slave:02x}: detected "
                f"but all read modes failed")
    return False


def _discover_nvmem_class(bf3) -> bool:
    """Find EEPROM via /sys/class/nvmem (covers at24, spd5118, etc.)."""
    r = bf3.execute(
        "ls -d /sys/class/nvmem/*/nvmem 2>/dev/null || "
        "ls -d /sys/bus/nvmem/devices/*/nvmem 2>/dev/null")
    if r.rc != 0 or not r.stdout.strip():
        return False
    for path in r.stdout.strip().splitlines():
        path = path.strip()
        rd = bf3.execute(
            f"dd if={path} bs=1 count=1 "
            f"2>/dev/null | od -A n -t x1")
        if rd.rc == 0 and rd.stdout.strip():
            _eeprom["path"] = path
            sz = bf3.execute(f"wc -c < {path} 2>/dev/null")
            _eeprom["size"] = (
                int(sz.stdout.strip()) if sz.rc == 0 else 0)
            _eeprom["method"] = "sysfs"
            logger.info(f"EEPROM via nvmem class: {path}")
            return True
    return False


def _log_diagnostics(bf3):
    """Log detailed I2C/EEPROM diagnostic info when discovery fails."""
    logger.info("=== EEPROM Discovery Diagnostics ===")

    r = bf3.execute("ls -la /sys/bus/i2c/devices/ 2>/dev/null")
    logger.info(f"I2C devices:\n{r.stdout}")

    r = bf3.execute(
        "for d in /sys/bus/i2c/devices/[0-9]*; do "
        "echo \"$(basename $d): $(cat $d/name 2>/dev/null) "
        "driver=$(basename $(readlink $d/driver 2>/dev/null) "
        "2>/dev/null)\"; done 2>/dev/null")
    logger.info(f"I2C device details:\n{r.stdout}")

    r = bf3.execute(
        "ls /sys/bus/i2c/devices/*/eeprom "
        "/sys/bus/i2c/devices/*/nvmem "
        "/sys/class/nvmem/*/nvmem "
        "/sys/bus/nvmem/devices/*/nvmem 2>/dev/null || "
        "echo 'No sysfs eeprom/nvmem found'")
    logger.info(f"Sysfs EEPROM/nvmem paths:\n{r.stdout}")

    r = bf3.execute(
        "lsmod | grep -iE 'eeprom|at24|spd|nvmem|i2c' "
        "2>/dev/null || echo 'no matching modules'")
    logger.info(f"Loaded I2C/EEPROM modules:\n{r.stdout}")

    r = bf3.execute("ls /dev/i2c-* 2>/dev/null")
    if r.rc == 0:
        for dev in r.stdout.strip().split():
            bus = dev.rsplit("-", 1)[1]
            det = bf3.execute(f"i2cdetect -y {bus} 2>/dev/null")
            logger.info(f"i2cdetect bus {bus}:\n{det.stdout}")

    # Show actual error from a representative read attempt
    r = bf3.execute("ls /dev/i2c-* 2>/dev/null")
    if r.rc == 0:
        buses = r.stdout.strip().split()
        if buses:
            bus = buses[0].rsplit("-", 1)[1]
            rd = bf3.execute(
                f"i2cget -f -y {bus} 0x50 0x00 2>&1")
            logger.info(
                f"i2cget error sample (bus {bus}, 0x50): "
                f"rc={rd.rc} out={rd.stdout!r}")

    logger.info("=== End Diagnostics ===")


def _require_eeprom():
    if _eeprom["method"] is None:
        pytest.skip("No accessible EEPROM discovered")


def _read_byte(bf3, offset: int) -> str:
    if _eeprom["method"] == "sysfs":
        r = bf3.execute(
            f"dd if={_eeprom['path']} bs=1 count=1 "
            f"skip={offset} 2>/dev/null | od -A n -t x1")
        return r.stdout.strip() if r.rc == 0 else ""
    else:
        bus, slave = _eeprom["bus"], _eeprom["slave"]
        r = bf3.execute(
            f"i2cget -f -y {bus} 0x{slave:02x} "
            f"0x{offset:02x}")
        return r.stdout.strip() if r.rc == 0 else ""


def _write_byte(bf3, offset: int, val: int) -> bool:
    if _eeprom["method"] == "sysfs":
        r = bf3.execute(
            f"printf '\\x{val:02x}' | "
            f"dd of={_eeprom['path']} bs=1 count=1 "
            f"seek={offset} conv=notrunc 2>/dev/null")
        return r.rc == 0
    else:
        bus, slave = _eeprom["bus"], _eeprom["slave"]
        r = bf3.execute(
            f"i2cset -f -y {bus} 0x{slave:02x} "
            f"0x{offset:02x} 0x{val:02x}")
        return r.rc == 0


class TestEEPROM:
    """I2C EEPROM tests on BF3 DPU ARM (port of old_test/eeprom.c)."""

    @pytest.mark.p0
    def test_i2c_tools_available(self, bf3):
        """EEPROM-001: i2c-tools are installed."""
        result = bf3.execute("which i2cdetect i2cget i2cset")
        assert result.rc == 0, (
            "i2c-tools not found — install with: "
            "apt-get install -y i2c-tools")

    @pytest.mark.p0
    def test_eeprom_discover(self, bf3):
        """EEPROM-002: Find an accessible EEPROM.

        Priority: testbed config > sysfs > nvmem class > raw I2C.
        Logs full diagnostics on failure.
        """
        cfg = bf3.config.get("eeprom", {})
        if cfg.get("sysfs_path"):
            _eeprom["path"] = cfg["sysfs_path"]
            _eeprom["method"] = "sysfs"
            sz = bf3.execute(
                f"wc -c < {_eeprom['path']} 2>/dev/null")
            _eeprom["size"] = (
                int(sz.stdout.strip()) if sz.rc == 0 else 0)
            logger.info(f"Using config sysfs: {_eeprom['path']}")
            return
        if cfg.get("i2c_bus") is not None:
            _eeprom["bus"] = cfg["i2c_bus"]
            _eeprom["slave"] = cfg.get("slave_addr", 0x50)
            _eeprom["method"] = "i2c"
            logger.info(f"Using config i2c: bus={_eeprom['bus']} "
                         f"slave=0x{_eeprom['slave']:02x}")
            return

        # Try loading at24 / eeprom modules if not already loaded
        bf3.execute("modprobe at24 2>/dev/null; "
                     "modprobe eeprom 2>/dev/null")

        if _discover_sysfs(bf3):
            return
        if _discover_nvmem_class(bf3):
            return
        if _discover_i2c(bf3):
            return

        _log_diagnostics(bf3)
        pytest.skip("No user-accessible EEPROM on this DPU — "
                     "I2C buses only have IPMI/IPMB controllers. "
                     "Set eeprom.sysfs_path or eeprom.i2c_bus in "
                     "testbed config to override.")

    @pytest.mark.p0
    def test_eeprom_read(self, bf3):
        """EEPROM-003: Can read bytes from the EEPROM."""
        _require_eeprom()
        val = _read_byte(bf3, 0)
        assert val, "EEPROM read at offset 0 returned empty"
        logger.info(f"EEPROM[0x00] = {val}")

    @pytest.mark.p1
    def test_eeprom_dump(self, bf3):
        """EEPROM-004: Dump first 128 bytes of EEPROM."""
        _require_eeprom()
        if _eeprom["method"] == "sysfs":
            r = bf3.execute(
                f"dd if={_eeprom['path']} bs=1 count=128 "
                f"2>/dev/null | od -A x -t x1z")
        else:
            bus, slave = _eeprom["bus"], _eeprom["slave"]
            r = bf3.execute(
                f"i2cdump -f -y -r 0x00-0x7f {bus} "
                f"0x{slave:02x} b",
                timeout=30)
        assert r.rc == 0, f"EEPROM dump failed: {r.stderr}"
        assert r.stdout.strip(), "Empty EEPROM dump"
        logger.info(f"EEPROM dump:\n{r.stdout}")

    @pytest.mark.p1
    @pytest.mark.destructive
    def test_eeprom_write_readback(self, bf3):
        """EEPROM-005: Write/readback verify (scratch region).

        Ported from old_test/eeprom.c random R/W test.
        Uses a safe scratch region at offset 0xF0-0xFF,
        saves originals, writes test patterns, reads back,
        then restores.
        """
        _require_eeprom()

        probe = _read_byte(bf3, SCRATCH_OFFSET)
        if not probe:
            pytest.skip("Cannot read scratch region")

        saved = {}
        for offset in range(SCRATCH_OFFSET,
                            SCRATCH_OFFSET + SCRATCH_LEN):
            val = _read_byte(bf3, offset)
            if val:
                saved[offset] = val

        if not saved:
            pytest.skip("Cannot read scratch region")

        try:
            errors = []
            rng = random.Random(42)
            for _ in range(RANDOM_RW_TEST_COUNT):
                addr = SCRATCH_OFFSET + rng.randint(
                    0, SCRATCH_LEN - 1)
                val = addr & 0xFF
                if not _write_byte(bf3, addr, val):
                    errors.append(
                        f"addr 0x{addr:02x}: write failed")
                    continue
                time.sleep(0.01)
                readback = _read_byte(bf3, addr)
                expected = f"{val:02x}"
                if expected not in readback:
                    errors.append(
                        f"addr 0x{addr:02x}: wrote 0x{expected}"
                        f" read {readback!r}")
                    logger.error(errors[-1])

            assert not errors, (
                f"{len(errors)}/{RANDOM_RW_TEST_COUNT} "
                f"mismatches: {errors[:5]}")
            logger.info(f"EEPROM write/readback: "
                         f"{RANDOM_RW_TEST_COUNT} OK")
        finally:
            for offset, orig in saved.items():
                if _eeprom["method"] == "sysfs":
                    orig_int = int(orig.strip(), 16)
                    _write_byte(bf3, offset, orig_int)
                else:
                    bf3.execute(
                        f"i2cset -f -y {_eeprom['bus']} "
                        f"0x{_eeprom['slave']:02x} "
                        f"0x{offset:02x} {orig}")
            logger.info("Restored scratch region")

    @pytest.mark.p2
    @pytest.mark.destructive
    def test_eeprom_multi_bank(self, bf3):
        """EEPROM-006: Multi-bank read (if configured)."""
        _require_eeprom()
        banks = bf3.config.get("eeprom", {}).get("banks", 1)
        if banks <= 1:
            pytest.skip("Single-bank EEPROM")
        if _eeprom["method"] != "i2c":
            pytest.skip("Multi-bank only for raw I2C mode")
        bus, slave = _eeprom["bus"], _eeprom["slave"]
        for bank in range(banks):
            bank_slave = slave + bank
            r = bf3.execute(
                f"i2cget -f -y {bus} 0x{bank_slave:02x} 0x00")
            assert r.rc == 0, (
                f"Bank {bank} (0x{bank_slave:02x}) read failed")
            logger.info(f"Bank {bank} (0x{bank_slave:02x}): "
                         f"byte 0x00 = {r.stdout.strip()}")
