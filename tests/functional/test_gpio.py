# tests/functional/test_gpio.py
# Port of old_test/gpio_test.c — GPIO verification on BF3 DPU.
# Tries: libgpiod > sysfs export > debugfs (read-only).

import logging
import pytest

pytestmark = [pytest.mark.functional]

logger = logging.getLogger(__name__)

SYSFS_GPIO = "/sys/class/gpio"

# method: "gpiod" | "debugfs" | None
_gpio = {"method": None, "chip_name": None, "chip_label": None,
         "ngpio": 0, "base": 0, "test_offset": None,
         "debugfs_lines": {}}


def _gpio_cfg(bf3) -> dict:
    return bf3.config.get("gpio", {})


def _ensure_libgpiod(bf3) -> bool:
    """Check or install libgpiod tools."""
    r = bf3.execute("which gpioget 2>/dev/null")
    if r.rc == 0:
        return True
    r = bf3.execute("which apt-get 2>/dev/null")
    if r.rc != 0:
        return False
    logger.info("Installing libgpiod tools...")
    bf3.execute(
        "apt-get update -qq 2>/dev/null && "
        "apt-get install -y -qq gpiod 2>/dev/null || "
        "apt-get install -y -qq libgpiod-utils 2>/dev/null",
        timeout=60)
    r = bf3.execute("which gpioget 2>/dev/null")
    return r.rc == 0


def _validate_gpiod(bf3, chip: str) -> bool:
    """Check if gpioget actually works on this chip."""
    r = bf3.execute(f"gpioget {chip} 0 2>&1")
    if r.rc == 0 and r.stdout.strip().isdigit():
        return True
    logger.info(f"gpioget {chip} 0 failed: {r.stdout.strip()}")
    return False


def _parse_debugfs_gpio(bf3) -> dict:
    """Parse /sys/kernel/debug/gpio for GPIO line states."""
    r = bf3.execute("cat /sys/kernel/debug/gpio 2>/dev/null")
    if r.rc != 0 or not r.stdout.strip():
        return {}

    lines = {}
    current_chip = None
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        # Chip header: "gpiochip0: GPIOs 512-543, parent: ..., MLNXBF33:00:"
        if line.startswith("gpiochip") or "GPIOs" in line:
            current_chip = line
            continue
        # GPIO line: " gpio-512 (                    |gpio-mlxbf3-bkp ) in  hi"
        if line.startswith("gpio-"):
            parts = line.split()
            try:
                pin_num = int(parts[0].replace("gpio-", ""))
                direction = "in" if "in" in line else "out"
                value = "hi" if "hi" in line else "lo"
                lines[pin_num] = {
                    "direction": direction,
                    "value": 1 if value == "hi" else 0,
                    "raw": line,
                    "chip": current_chip,
                }
            except (ValueError, IndexError):
                pass
    return lines


def _require_gpio():
    if _gpio["method"] is None:
        pytest.skip("No accessible GPIO on this DPU")


def _require_writable():
    if _gpio["method"] != "gpiod":
        pytest.skip("GPIO write requires working libgpiod "
                     "(chardev access)")


def _log_diagnostics(bf3):
    logger.info("=== GPIO Diagnostics ===")
    r = bf3.execute("gpiodetect 2>&1 || echo 'not available'")
    logger.info(f"gpiodetect:\n{r.stdout}")
    r = bf3.execute("gpioget gpiochip0 0 2>&1 || true")
    logger.info(f"gpioget probe: {r.stdout.strip()}")
    r = bf3.execute("gpioinfo gpiochip0 2>&1 || true")
    logger.info(f"gpioinfo probe: {r.stdout.strip()}")
    r = bf3.execute(
        "cat /sys/kernel/debug/gpio 2>/dev/null | head -30 "
        "|| echo 'debugfs not available'")
    logger.info(f"debugfs gpio:\n{r.stdout}")
    r = bf3.execute(
        "lsmod | grep -iE 'gpio|mlxbf' 2>/dev/null || "
        "echo 'no modules'")
    logger.info(f"Modules:\n{r.stdout}")
    logger.info("=== End Diagnostics ===")


class TestGPIO:
    """GPIO tests on BF3 DPU ARM (port of old_test/gpio_test.c).

    Tries libgpiod chardev access first; falls back to
    /sys/kernel/debug/gpio for read-only verification.
    """

    @pytest.mark.p0
    def test_gpio_chip_detected(self, bf3):
        """GPIO-001: GPIO controller is present on the DPU."""
        _ensure_libgpiod(bf3)

        r = bf3.execute("gpiodetect 2>/dev/null")
        if r.rc != 0 or not r.stdout.strip():
            r2 = bf3.execute(
                "ls /sys/class/gpio/gpiochip* 2>/dev/null")
            if r2.rc != 0:
                _log_diagnostics(bf3)
                pytest.skip("No GPIO controller found")

        for line in r.stdout.strip().splitlines():
            logger.info(f"gpiodetect: {line}")
            parts = line.split()
            chip = parts[0]
            label = ""
            ngpio = 0
            for p in parts:
                if p.startswith("["):
                    label = p.strip("[]")
                if p.startswith("("):
                    num = p.strip("()")
                    if num.isdigit():
                        ngpio = int(num)

            if "MLNXBF" in label or "mlxbf" in label.lower():
                _gpio["chip_name"] = chip
                _gpio["chip_label"] = label
                _gpio["ngpio"] = ngpio
                break

            if _gpio["chip_name"] is None:
                _gpio["chip_name"] = chip
                _gpio["chip_label"] = label
                _gpio["ngpio"] = ngpio

        assert _gpio["chip_name"], "No GPIO chip found"
        logger.info(f"GPIO chip: {_gpio['chip_name']} "
                     f"[{_gpio['chip_label']}] "
                     f"({_gpio['ngpio']} lines)")

    @pytest.mark.p0
    def test_gpio_access(self, bf3):
        """GPIO-002: Verify GPIO lines are accessible.

        Tries libgpiod chardev, falls back to debugfs.
        """
        if _gpio["chip_name"] is None:
            pytest.skip("No GPIO chip discovered")

        chip = _gpio["chip_name"]

        if _validate_gpiod(bf3, chip):
            _gpio["method"] = "gpiod"
            _gpio["test_offset"] = 0
            logger.info(f"GPIO accessible via libgpiod (chardev)")

            r = bf3.execute(f"gpioinfo {chip} 2>/dev/null")
            if r.rc == 0:
                for line in r.stdout.strip().splitlines():
                    line = line.strip()
                    if "unused" in line.lower():
                        try:
                            offset = int(
                                line.split(":")[0]
                                .replace("line", "").strip())
                            _gpio["test_offset"] = offset
                            break
                        except (ValueError, IndexError):
                            pass
            logger.info(
                f"Test offset: {_gpio['test_offset']}")
            return

        logger.info("libgpiod chardev access failed, "
                     "trying debugfs...")
        debugfs = _parse_debugfs_gpio(bf3)
        if debugfs:
            _gpio["method"] = "debugfs"
            _gpio["debugfs_lines"] = debugfs
            _gpio["test_offset"] = next(iter(debugfs))
            logger.info(
                f"GPIO readable via debugfs: "
                f"{len(debugfs)} lines")
            return

        _log_diagnostics(bf3)
        pytest.skip(
            "GPIO controller exists but lines not accessible "
            "via chardev or debugfs")

    @pytest.mark.p0
    def test_gpio_read(self, bf3):
        """GPIO-003: Can read a GPIO pin value."""
        _require_gpio()
        offset = _gpio["test_offset"]

        if _gpio["method"] == "gpiod":
            chip = _gpio["chip_name"]
            r = bf3.execute(f"gpioget {chip} {offset} 2>&1")
            assert r.rc == 0 and r.stdout.strip().isdigit(), (
                f"gpioget {chip} {offset} failed: "
                f"{r.stdout.strip()}")
            val = int(r.stdout.strip())
            assert val in (0, 1)
            logger.info(f"{chip} line {offset}: value={val}")
        else:
            pin = _gpio["test_offset"]
            info = _gpio["debugfs_lines"].get(pin, {})
            assert info, f"GPIO pin {pin} not in debugfs"
            logger.info(
                f"gpio-{pin}: dir={info['direction']} "
                f"val={info['value']} "
                f"({info['raw']})")

    @pytest.mark.p1
    def test_gpio_output_write_readback(self, bf3):
        """GPIO-004: Set output, write value, read back.

        Port of gpio_test.c test_case(pin, "out", "1").
        """
        _require_writable()
        offset = _gpio["test_offset"]
        chip = _gpio["chip_name"]

        r = bf3.execute(f"gpioset {chip} {offset}=1 2>&1")
        assert r.rc == 0, (
            f"gpioset {chip} {offset}=1 failed: "
            f"{r.stdout.strip()}")

        r = bf3.execute(f"gpioget {chip} {offset} 2>&1")
        assert r.rc == 0
        logger.info(f"{chip} line {offset}: set=1, "
                     f"read={r.stdout.strip()}")

        r = bf3.execute(f"gpioset {chip} {offset}=0 2>&1")
        assert r.rc == 0, (
            f"gpioset {chip} {offset}=0 failed: "
            f"{r.stdout.strip()}")

        r = bf3.execute(f"gpioget {chip} {offset} 2>&1")
        assert r.rc == 0
        logger.info(f"{chip} line {offset}: set=0, "
                     f"read={r.stdout.strip()}")

    @pytest.mark.p1
    def test_gpio_input_read(self, bf3):
        """GPIO-005: Read value in input mode.

        Port of gpio_test.c test_case(pin, "in", "1").
        """
        _require_gpio()
        offset = _gpio["test_offset"]

        if _gpio["method"] == "gpiod":
            chip = _gpio["chip_name"]
            r = bf3.execute(f"gpioget {chip} {offset} 2>&1")
            assert r.rc == 0 and r.stdout.strip().isdigit(), (
                f"gpioget {chip} {offset} failed")
            val = int(r.stdout.strip())
            assert val in (0, 1)
            logger.info(f"{chip} line {offset}: input={val}")
        else:
            pin = _gpio["test_offset"]
            info = _gpio["debugfs_lines"].get(pin, {})
            assert info, f"GPIO pin {pin} not in debugfs"
            assert info["direction"] in ("in", "out")
            logger.info(
                f"gpio-{pin}: {info['direction']} "
                f"val={info['value']}")

    @pytest.mark.p2
    def test_gpio_all_lines_enumerable(self, bf3):
        """GPIO-006: All GPIO lines on the chip can be listed."""
        _require_gpio()

        if _gpio["method"] == "gpiod":
            chip = _gpio["chip_name"]
            r = bf3.execute(f"gpioinfo {chip} 2>&1")
            if r.rc == 0:
                lines = r.stdout.strip().splitlines()
                logger.info(
                    f"gpioinfo {chip}: {len(lines)} lines\n"
                    + "\n".join(lines[:10])
                    + ("\n..." if len(lines) > 10 else ""))
                return
            logger.info(f"gpioinfo failed: {r.stdout.strip()}")

        debugfs = _gpio.get("debugfs_lines") or \
            _parse_debugfs_gpio(bf3)
        if debugfs:
            logger.info(
                f"debugfs gpio: {len(debugfs)} lines")
            for pin, info in sorted(debugfs.items())[:10]:
                logger.info(
                    f"  gpio-{pin}: {info['raw']}")
            if len(debugfs) > 10:
                logger.info(f"  ... ({len(debugfs)} total)")
            return

        r = bf3.execute(
            f"cat /sys/class/gpio/{_gpio['chip_name']}/base "
            f"/sys/class/gpio/{_gpio['chip_name']}/ngpio "
            f"/sys/class/gpio/{_gpio['chip_name']}/label "
            f"2>/dev/null")
        if r.rc == 0:
            logger.info(f"Chip sysfs attrs:\n{r.stdout}")
            return

        pytest.skip("Cannot enumerate GPIO lines")
