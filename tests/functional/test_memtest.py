# tests/functional/test_memtest.py
# Port of old_test/memtest.c — Memory integrity verification on BF3 DPU.
# Uses memtester for pattern write/readback; checks ECC/EDAC for HW errors.

import logging
import re
import pytest

pytestmark = [pytest.mark.functional]

logger = logging.getLogger(__name__)

_mem = {"total_kb": 0, "free_kb": 0, "available_kb": 0,
        "cpus": 0, "ecc_ce_before": 0, "ecc_ue_before": 0}


def _parse_meminfo(bf3) -> dict:
    r = bf3.execute("cat /proc/meminfo")
    assert r.rc == 0, "Cannot read /proc/meminfo"
    info = {}
    for line in r.stdout.splitlines():
        m = re.match(r"(\w+):\s+(\d+)\s+kB", line)
        if m:
            info[m.group(1)] = int(m.group(2))
    return info


def _get_ecc_counts(bf3) -> tuple[int, int]:
    """Return (correctable, uncorrectable) ECC error totals."""
    ce = 0
    ue = 0
    r = bf3.execute(
        "cat /sys/devices/system/edac/mc/mc*/ce_count "
        "2>/dev/null || echo 0")
    for val in r.stdout.split():
        if val.strip().isdigit():
            ce += int(val.strip())
    r = bf3.execute(
        "cat /sys/devices/system/edac/mc/mc*/ue_count "
        "2>/dev/null || echo 0")
    for val in r.stdout.split():
        if val.strip().isdigit():
            ue += int(val.strip())
    return ce, ue


def _ensure_memtester(bf3) -> bool:
    r = bf3.execute("which memtester 2>/dev/null")
    if r.rc == 0:
        return True
    r = bf3.execute("which apt-get 2>/dev/null")
    if r.rc != 0:
        return False
    logger.info("Installing memtester...")
    bf3.execute(
        "apt-get update -qq 2>/dev/null && "
        "apt-get install -y -qq memtester 2>/dev/null",
        timeout=60)
    r = bf3.execute("which memtester 2>/dev/null")
    return r.rc == 0


def _check_dmesg_errors(bf3) -> list[str]:
    r = bf3.execute(
        "dmesg | grep -iE "
        "'memory error|hardware error|mce|edac|"
        "uncorrectable|correctable|oom.killer' "
        "2>/dev/null | tail -20")
    if r.rc == 0 and r.stdout.strip():
        return r.stdout.strip().splitlines()
    return []


class TestMemory:
    """Memory tests on BF3 DPU ARM (port of old_test/memtest.c).

    Verifies memory integrity via pattern write/readback (memtester)
    and checks for ECC errors. Configurable via testbed yaml:

        memory:
          test_size_mb: 100     # MB to test (default: 100)
          passes: 1             # memtester iterations (default: 1)
          large_test_mb: 512    # for the large test (default: 512)
    """

    @pytest.mark.p0
    def test_memory_info(self, bf3):
        """MEM-001: Read and validate /proc/meminfo."""
        info = _parse_meminfo(bf3)

        _mem["total_kb"] = info.get("MemTotal", 0)
        _mem["free_kb"] = info.get("MemFree", 0)
        _mem["available_kb"] = info.get("MemAvailable", 0)

        assert _mem["total_kb"] > 0, "MemTotal is 0"
        total_gb = _mem["total_kb"] / (1024 * 1024)
        free_gb = _mem["free_kb"] / (1024 * 1024)
        avail_gb = _mem["available_kb"] / (1024 * 1024)
        logger.info(
            f"Memory: total={total_gb:.1f}GB "
            f"free={free_gb:.1f}GB "
            f"available={avail_gb:.1f}GB")

        r = bf3.execute("nproc 2>/dev/null")
        _mem["cpus"] = (
            int(r.stdout.strip()) if r.rc == 0 else 1)
        logger.info(f"CPUs: {_mem['cpus']}")

        assert _mem["available_kb"] > 64 * 1024, (
            f"Less than 64MB available "
            f"({_mem['available_kb'] // 1024}MB)")

    @pytest.mark.p0
    def test_memtester_available(self, bf3):
        """MEM-002: memtester tool is available."""
        if not _ensure_memtester(bf3):
            pytest.skip(
                "memtester not available and cannot be "
                "installed")
        r = bf3.execute("memtester 2>&1 | head -1")
        logger.info(f"memtester: {r.stdout.strip()}")

    @pytest.mark.p0
    def test_ecc_status(self, bf3):
        """MEM-003: Check ECC/EDAC status before tests."""
        ce, ue = _get_ecc_counts(bf3)
        _mem["ecc_ce_before"] = ce
        _mem["ecc_ue_before"] = ue
        logger.info(
            f"ECC before: correctable={ce}, "
            f"uncorrectable={ue}")
        if ue > 0:
            logger.warning(
                f"{ue} pre-existing uncorrectable ECC errors!")

        r = bf3.execute(
            "ls /sys/devices/system/edac/mc/ 2>/dev/null")
        if r.rc == 0 and r.stdout.strip():
            logger.info(f"EDAC controllers: {r.stdout.strip()}")
        else:
            logger.info("No EDAC memory controllers found "
                         "(ECC may not be exposed)")

    @pytest.mark.p1
    def test_memtest_small(self, bf3):
        """MEM-004: Quick memory test (small allocation).

        Port of memtest.sh: ./memtest.armexe -p 1 -s 10m
        """
        r = bf3.execute("which memtester 2>/dev/null")
        if r.rc != 0:
            pytest.skip("memtester not installed")

        cfg = bf3.config.get("memory", {})
        size_mb = cfg.get("test_size_mb", 10)
        passes = cfg.get("passes", 1)

        logger.info(f"Running memtester {size_mb}M {passes}...")
        result = bf3.execute(
            f"memtester {size_mb}M {passes} 2>&1",
            timeout=300)
        logger.info(f"memtester output:\n{result.stdout}")

        assert result.rc == 0, (
            f"memtester failed (rc={result.rc}). "
            f"Output:\n{result.stdout[-500:]}")

        assert "FAILURE" not in result.stdout.upper(), (
            f"memtester reported failures:\n"
            f"{result.stdout[-500:]}")
        logger.info(f"memtester {size_mb}M x{passes}: PASSED")

    @pytest.mark.p1
    def test_memtest_medium(self, bf3):
        """MEM-005: Medium memory test (100MB).

        Port of memtest.sh: ./memtest.armexe -p 1 -s 100m
        """
        r = bf3.execute("which memtester 2>/dev/null")
        if r.rc != 0:
            pytest.skip("memtester not installed")

        cfg = bf3.config.get("memory", {})
        size_mb = cfg.get("medium_test_mb", 100)
        passes = cfg.get("passes", 1)

        logger.info(f"Running memtester {size_mb}M {passes}...")
        result = bf3.execute(
            f"memtester {size_mb}M {passes} 2>&1",
            timeout=600)

        last_lines = "\n".join(
            result.stdout.strip().splitlines()[-10:])
        logger.info(f"memtester tail:\n{last_lines}")

        assert result.rc == 0, (
            f"memtester failed (rc={result.rc})")
        assert "FAILURE" not in result.stdout.upper(), (
            f"memtester reported failures")
        logger.info(f"memtester {size_mb}M x{passes}: PASSED")

    @pytest.mark.p2
    def test_memtest_large(self, bf3):
        """MEM-006: Large memory stress test.

        Tests a larger portion of free RAM, similar to the
        original memtest.c default behavior.
        """
        r = bf3.execute("which memtester 2>/dev/null")
        if r.rc != 0:
            pytest.skip("memtester not installed")

        cfg = bf3.config.get("memory", {})
        size_mb = cfg.get("large_test_mb", 512)
        passes = cfg.get("passes", 1)

        avail_mb = _mem.get("available_kb", 0) // 1024
        if avail_mb == 0:
            info = _parse_meminfo(bf3)
            avail_mb = info.get("MemAvailable", 0) // 1024

        reserve_mb = max(512, avail_mb // 8)
        max_test_mb = avail_mb - reserve_mb
        if size_mb > max_test_mb:
            size_mb = max(64, max_test_mb)
            logger.info(
                f"Reduced test size to {size_mb}MB "
                f"(available={avail_mb}MB, "
                f"reserve={reserve_mb}MB)")

        logger.info(
            f"Running memtester {size_mb}M {passes} "
            f"(large test)...")
        result = bf3.execute(
            f"memtester {size_mb}M {passes} 2>&1",
            timeout=1200)

        last_lines = "\n".join(
            result.stdout.strip().splitlines()[-10:])
        logger.info(f"memtester tail:\n{last_lines}")

        assert result.rc == 0, (
            f"memtester failed (rc={result.rc})")
        assert "FAILURE" not in result.stdout.upper(), (
            f"memtester reported failures")
        logger.info(f"memtester {size_mb}M x{passes}: PASSED")

    @pytest.mark.p1
    def test_no_new_ecc_errors(self, bf3):
        """MEM-007: No new ECC errors after memory tests."""
        ce, ue = _get_ecc_counts(bf3)
        new_ce = ce - _mem.get("ecc_ce_before", 0)
        new_ue = ue - _mem.get("ecc_ue_before", 0)
        logger.info(
            f"ECC after: correctable={ce} (+{new_ce}), "
            f"uncorrectable={ue} (+{new_ue})")

        assert new_ue == 0, (
            f"{new_ue} new uncorrectable ECC errors "
            f"during memory test!")
        if new_ce > 0:
            logger.warning(
                f"{new_ce} new correctable ECC errors "
                f"(not fatal but worth investigating)")

    @pytest.mark.p1
    def test_no_dmesg_memory_errors(self, bf3):
        """MEM-008: No memory-related errors in dmesg."""
        errors = _check_dmesg_errors(bf3)
        if errors:
            for line in errors:
                logger.warning(f"dmesg: {line}")
        oom = [e for e in errors if "oom" in e.lower()]
        hw_err = [e for e in errors
                  if "uncorrectable" in e.lower()
                  or "hardware error" in e.lower()]
        assert not oom, (
            f"OOM killer was invoked: {oom[0]}")
        assert not hw_err, (
            f"Hardware memory errors in dmesg: {hw_err[0]}")
        if errors:
            logger.info(
                f"{len(errors)} memory-related dmesg lines "
                f"(no critical errors)")
        else:
            logger.info("No memory errors in dmesg")
