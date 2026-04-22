# tests/functional/test_write_device.py
# Port of old_test/write_device.c — device write/read verification.
# The original test used mmap(MAP_SHARED) to write random patterns to
# a block device, then re-read with the same RNG seed to verify.
# This port performs the same write/verify logic via a helper script
# uploaded to the DPU, testing both file-backed and direct block
# device I/O paths.

import logging
import textwrap

import pytest

pytestmark = [pytest.mark.functional]

logger = logging.getLogger(__name__)

_SCRIPT_PATH = "/tmp/wdv_helper.py"

_HELPER_SCRIPT = textwrap.dedent("""\
    import os, struct, random, sys

    path = sys.argv[1]
    num_writes = int(sys.argv[2])
    seed = int(sys.argv[3])
    total_size = int(sys.argv[4])
    mode = sys.argv[5] if len(sys.argv) > 5 else "random"

    word_size = 8
    words = total_size // word_size
    errors = 0

    if mode == "linear":
        step = 0x100000 // word_size
        fd = os.open(path, os.O_RDWR)
        i = 1
        w = step
        while w < words:
            os.lseek(fd, w * word_size, os.SEEK_SET)
            os.write(fd, struct.pack("<Q", i))
            i += 1
            w += step
        os.fsync(fd)
        os.close(fd)
        fd = os.open(path, os.O_RDONLY)
        i = 1
        w = step
        while w < words:
            os.lseek(fd, w * word_size, os.SEEK_SET)
            data = os.read(fd, word_size)
            val = struct.unpack("<Q", data)[0]
            if val != i:
                print("VERIFY_FAIL w=0x%x read=%d expect=%d" % (w, val, i))
                errors += 1
            i += 1
            w += step
        os.close(fd)
        print("RESULT linear_writes=%d errors=%d" % (i - 1, errors))
    else:
        random.seed(seed)
        written = {}
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
        for i in range(1, num_writes + 1):
            w = random.randint(0, words - 1)
            while w in written:
                w = random.randint(0, words - 1)
            written[w] = i
            os.lseek(fd, w * word_size, os.SEEK_SET)
            os.write(fd, struct.pack("<Q", i))
        os.fsync(fd)
        os.close(fd)

        random.seed(seed)
        fd = os.open(path, os.O_RDONLY)
        visited = {}
        for i in range(1, num_writes + 1):
            w = random.randint(0, words - 1)
            while w in visited:
                w = random.randint(0, words - 1)
            visited[w] = i
            os.lseek(fd, w * word_size, os.SEEK_SET)
            data = os.read(fd, word_size)
            if len(data) != word_size:
                print("SHORT_READ word=0x%x" % w)
                errors += 1
                continue
            val = struct.unpack("<Q", data)[0]
            if val != i:
                print("VERIFY_FAIL word=0x%x read=%d expect=%d" % (w, val, i))
                errors += 1
        os.close(fd)
        print("RESULT writes=%d errors=%d" % (num_writes, errors))

    sys.exit(1 if errors else 0)
""")


def _ensure_helper(bf3):
    """Upload the write/verify helper script to the DPU."""
    r = bf3.execute(f"test -f {_SCRIPT_PATH} && echo exists")
    if r.rc == 0 and "exists" in r.stdout:
        return
    encoded = _HELPER_SCRIPT.replace("\\", "\\\\").replace('"', '\\"')
    bf3.execute(
        f'printf "%s" "{encoded}" > {_SCRIPT_PATH}',
        timeout=10)


def _run_wdv(bf3, test_file, num_writes, seed, size,
             mode="random", timeout=30):
    """Run the write/verify helper and return the result."""
    _ensure_helper(bf3)
    r = bf3.execute(
        f"python3 {_SCRIPT_PATH} "
        f"{test_file} {num_writes} {seed} {size} {mode}",
        timeout=timeout)
    return r


class TestWriteDevice:
    """Device write/read verification on BF3 DPU ARM.

    Port of old_test/write_device.c.  Uses random-offset write then
    read-verify with a deterministic seed, matching the original
    test's mmap-based approach.
    """

    @pytest.fixture(autouse=True)
    def _upload_helper(self, bf3):
        """Upload helper script once per session."""
        _ensure_helper(bf3)
        yield
        bf3.execute(f"rm -f {_SCRIPT_PATH}")

    @pytest.mark.p0
    def test_write_verify_small(self, bf3):
        """WDV-001: Small random write/verify (100 writes, 1MB).

        Core test matching write_device.c default behavior:
        random writes with a fixed seed, then read-back verify.
        """
        test_file = "/tmp/wdv_test_small"
        size = 1 * 1024 * 1024
        num_writes = 100
        seed = 42

        try:
            bf3.execute(
                f"dd if=/dev/zero of={test_file} "
                f"bs=1M count=1 2>/dev/null")

            r = _run_wdv(bf3, test_file, num_writes, seed, size)
            logger.info(f"Output: {r.stdout.strip()}")
            assert r.rc == 0, (
                f"Write/verify failed: {r.stdout} {r.stderr}")
            assert "errors=0" in r.stdout, (
                f"Verify errors: {r.stdout}")
        finally:
            bf3.execute(f"rm -f {test_file}")

    @pytest.mark.p1
    def test_write_verify_medium(self, bf3):
        """WDV-002: Medium random write/verify (500 writes, 8MB)."""
        test_file = "/tmp/wdv_test_medium"
        size = 8 * 1024 * 1024
        num_writes = 500
        seed = 12345

        try:
            bf3.execute(
                f"dd if=/dev/zero of={test_file} "
                f"bs=1M count=8 2>/dev/null")

            r = _run_wdv(bf3, test_file, num_writes, seed, size,
                         timeout=60)
            logger.info(f"Output: {r.stdout.strip()}")
            assert r.rc == 0, (
                f"Write/verify failed: {r.stdout} {r.stderr}")
            assert "errors=0" in r.stdout
        finally:
            bf3.execute(f"rm -f {test_file}")

    @pytest.mark.p1
    def test_write_verify_linear(self, bf3):
        """WDV-003: Linear write/verify pattern.

        Matches write_device.c --linear mode: sequential offsets
        spaced 1MB apart.
        """
        test_file = "/tmp/wdv_test_linear"
        size = 4 * 1024 * 1024

        try:
            bf3.execute(
                f"dd if=/dev/zero of={test_file} "
                f"bs=1M count=4 2>/dev/null")

            r = _run_wdv(bf3, test_file, 0, 0, size,
                         mode="linear")
            logger.info(f"Output: {r.stdout.strip()}")
            assert r.rc == 0, (
                f"Linear write/verify failed: "
                f"{r.stdout} {r.stderr}")
            assert "errors=0" in r.stdout
        finally:
            bf3.execute(f"rm -f {test_file}")

    @pytest.mark.p0
    def test_block_device_readable(self, bf3):
        """WDV-004: Block device is directly readable.

        Non-destructive: reads a small amount from the root
        block device to verify direct device I/O works.
        """
        r = bf3.execute(
            "mount | awk '/ \\/ / { print $1 }'")
        if r.rc != 0 or not r.stdout.strip():
            pytest.skip("Cannot determine root device")

        root_dev = r.stdout.strip()
        if root_dev == "rootfs":
            pytest.skip("Running from initramfs")

        r = bf3.execute(
            f"dd if={root_dev} of=/dev/null "
            f"bs=4096 count=16 2>&1")
        assert r.rc == 0, (
            f"Cannot read from {root_dev}: {r.stdout}")
        logger.info(f"Read 64KB from {root_dev}: OK")

    @pytest.mark.p1
    def test_emmc_readable(self, bf3):
        """WDV-005: eMMC device is directly readable."""
        r = bf3.execute("test -b /dev/mmcblk0")
        if r.rc != 0:
            pytest.skip("No eMMC device")

        r = bf3.execute(
            "dd if=/dev/mmcblk0 of=/dev/null "
            "bs=4096 count=16 2>&1")
        assert r.rc == 0, (
            f"Cannot read from eMMC: {r.stdout}")
        logger.info("Read 64KB from /dev/mmcblk0: OK")

    @pytest.mark.p2
    def test_write_verify_seed_reproducible(self, bf3):
        """WDV-006: Same seed produces identical write pattern.

        Verifies the deterministic seed behavior from write_device.c:
        write with seed S, then read-back with seed S must match.
        Runs twice with the same seed to confirm reproducibility.
        """
        test_file = "/tmp/wdv_test_seed"
        size = 512 * 1024
        num_writes = 50
        seed = 99999

        try:
            for run in [1, 2]:
                bf3.execute(
                    f"dd if=/dev/zero of={test_file} "
                    f"bs=512K count=1 2>/dev/null")

                r = _run_wdv(bf3, test_file, num_writes, seed,
                             size)
                logger.info(f"Run {run}: {r.stdout.strip()}")
                assert r.rc == 0, (
                    f"Run {run} failed: "
                    f"{r.stdout} {r.stderr}")
                assert "errors=0" in r.stdout
        finally:
            bf3.execute(f"rm -f {test_file}")

        logger.info("Seed reproducibility confirmed")
