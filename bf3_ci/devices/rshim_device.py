# bf3_ci/devices/rshim_device.py

import logging
import time
from bf3_ci.transport.ssh import SSHTransport

logger = logging.getLogger(__name__)


class RShimDevice:
    """RShim interface ? supports both host and BMC sources.

    BF3 can use RShim from:
    - Host (USB, /dev/rshim0)
    - BMC (internal, /dev/rshim0)
    """

    def __init__(self, transport: SSHTransport,
                 source: str = "host",
                 rshim_device: str = "/dev/rshim0"):
        self.transport = transport
        self.source = source  # "host" or "bmc"
        self.device = rshim_device

    def is_available(self) -> bool:
        result = self.transport.execute(
            f"test -e {self.device}/boot"
        )
        return result.rc == 0

    def push_bfb(self, bfb_path: str,
                 timeout: int = 1200) -> bool:
        """Push BFB through RShim."""
        logger.info(
            f"Pushing BFB via {self.source} RShim: "
            f"{bfb_path} -> {self.device}"
        )

        if self.source == "bmc":
            # For BMC RShim, file must be on BMC
            self.transport.scp_put(bfb_path,
                                    "/tmp/install.bfb")
            bfb_path = "/tmp/install.bfb"

        result = self.transport.execute(
            f"cat {bfb_path} > {self.device}/boot",
            timeout=timeout,
        )

        if self.source == "bmc":
            self.transport.execute("rm -f /tmp/install.bfb")

        if result.rc != 0:
            logger.error(f"BFB push failed: {result.stderr}")
            return False

        logger.info(
            f"BFB push completed in {result.duration:.0f}s"
        )
        return True

    def read_misc(self, key: str) -> str:
        """Read a value from rshim misc.

        Lines look like: DROP_MODE       0 (0:normal, 1:drop)
        Returns the second field (the actual value).
        """
        result = self.transport.execute(
            f"cat {self.device}/misc 2>/dev/null"
        )
        if result.rc != 0:
            return ""
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith(key):
                parts = stripped.split()
                return parts[1] if len(parts) > 1 else ""
        return ""

    def get_drop_mode(self) -> str:
        return self.read_misc("DROP_MODE")

    def get_display_level(self) -> str:
        return self.read_misc("DISPLAY_LEVEL")

    def set_display_level(self, level: int = 2) -> bool:
        """Set rshim misc DISPLAY_LEVEL (2=log shows INFO messages)."""
        result = self.transport.execute(
            f'echo "DISPLAY_LEVEL {level}" > {self.device}/misc',
            timeout=10,
        )
        if result.rc == 0:
            logger.info(f"Set rshim DISPLAY_LEVEL to {level}")
        else:
            logger.warning(
                f"Failed to set DISPLAY_LEVEL: {result.stderr}")
        return result.rc == 0

    def _read_misc_raw(self) -> str:
        result = self.transport.execute(
            f"timeout 10 cat {self.device}/misc 2>/dev/null",
            timeout=15,
        )
        if result.stdout:
            return result.stdout
        return ""

    def _check_install_done(self, misc_text: str) -> bool:
        """Check rshim misc log for the final completion marker.

        'DPU is ready' is the very last message, emitted after
        OS install AND all firmware updates (BMC/CEC/NIC FW)
        have finished.
        """
        return "DPU is ready" in misc_text

    def wait_for_bfb_complete(self, timeout: int = 2400,
                               interval: int = 30) -> bool:
        """Wait for BFB install to complete.

        Monitors the rshim misc log for 'DPU is ready',
        which is the final message after OS install and
        all firmware updates (BMC/CEC/NIC) finish.
        """
        self.set_display_level(2)

        deadline = time.time() + timeout
        seen_lines: set[str] = set()
        while time.time() < deadline:
            misc_text = self._read_misc_raw()

            for line in misc_text.splitlines():
                stripped = line.strip()
                if (stripped.startswith("INFO[")
                        and stripped not in seen_lines):
                    seen_lines.add(stripped)
                    logger.info(
                        f"[{self.source}] rshim: {stripped}")

            if self._check_install_done(misc_text):
                logger.info("BFB install complete "
                            "(DPU is ready)")
                return True

            time.sleep(interval)

        logger.error(
            f"BFB install timed out after {timeout}s")
        return False
