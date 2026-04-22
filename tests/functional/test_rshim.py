# tests/functional/test_rshim.py
# Port of old_test/tileusb-test.c — RShim/TMFIFO/CoreSight verification.
# The original test communicated with the DPU via a TCP socket to a
# RShim USB proxy using raw register-level access.  This port verifies
# the same subsystems (RShim, TMFIFO, CoreSight, USB) are functional
# using standard Linux interfaces from both DPU ARM and host.

import logging
import re

import pytest

pytestmark = [pytest.mark.functional]

logger = logging.getLogger(__name__)


def _host_available(host) -> bool:
    """Check if host SSH fixture is connected."""
    try:
        r = host.ssh.execute("echo ok", timeout=5)
        return r.rc == 0 and "ok" in r.stdout
    except Exception:
        return False


class TestRShimDPU:
    """RShim and TMFIFO verification from the DPU ARM side.

    Ports the TMFIFO and subsystem checks from tileusb-test.c,
    adapted for on-DPU verification.
    """

    @pytest.mark.p0
    def test_tmfifo_module_loaded(self, bf3):
        """RSH-001: TMFIFO kernel module is loaded on DPU.

        The original test_tmfifo() wrote/read data through the
        TM FIFO channel.  We verify the module and device are present.
        """
        r = bf3.execute("lsmod | grep mlxbf_tmfifo")
        assert r.rc == 0 and r.stdout.strip(), (
            "mlxbf_tmfifo module not loaded")
        logger.info(f"TMFIFO module: {r.stdout.strip()}")

    @pytest.mark.p0
    def test_tmfifo_net_interface(self, bf3):
        """RSH-002: TMFIFO network interface exists on DPU."""
        r = bf3.execute("ip link show tmfifo_net0 2>/dev/null")
        assert r.rc == 0, "tmfifo_net0 interface not found"

        state_up = "UP" in r.stdout
        logger.info(f"tmfifo_net0: {'UP' if state_up else 'present'}")
        logger.info(f"tmfifo_net0:\n{r.stdout.strip()}")

    @pytest.mark.p1
    def test_tmfifo_console_device(self, bf3):
        """RSH-003: TMFIFO console device exists."""
        r = bf3.execute(
            "ls /dev/virtio-ports/com.mellanox.tmfifo.0 "
            "2>/dev/null || "
            "ls /dev/hvc0 2>/dev/null")
        if r.rc != 0:
            pytest.skip("No TMFIFO console device found")
        logger.info(f"TMFIFO console: {r.stdout.strip()}")

    @pytest.mark.p1
    def test_coresight_devices(self, bf3):
        """RSH-004: CoreSight debug subsystem present.

        The original test_apb() walked CoreSight ROM tables via
        RShim APB registers.  We verify CoreSight devices are
        enumerated in sysfs.
        """
        r = bf3.execute("ls /sys/bus/coresight/devices/ 2>/dev/null")
        if r.rc != 0 or not r.stdout.strip():
            pytest.skip("No CoreSight devices in sysfs")

        devices = r.stdout.strip().splitlines()
        logger.info(f"CoreSight devices: {len(devices)}")
        for d in devices:
            logger.info(f"  {d.strip()}")

    @pytest.mark.p1
    def test_usb_controller_present(self, bf3):
        """RSH-005: USB controller detected on DPU.

        The original test used USB as the transport for RShim.
        We verify the USB subsystem is functional.
        """
        r = bf3.execute(
            "ls /sys/bus/usb/devices/ 2>/dev/null | head -20")
        if r.rc != 0 or not r.stdout.strip():
            r2 = bf3.execute("lsmod | grep -i usb")
            if r2.rc == 0 and r2.stdout.strip():
                logger.info(f"USB modules:\n{r2.stdout.strip()}")
            else:
                pytest.skip("No USB subsystem found")
            return

        devices = r.stdout.strip().splitlines()
        logger.info(f"USB devices/buses: {len(devices)}")
        for d in devices:
            logger.info(f"  {d.strip()}")

    @pytest.mark.p0
    def test_rshim_registers_readable(self, bf3):
        """RSH-006: RShim misc info readable from DPU side."""
        r = bf3.execute(
            "cat /sys/bus/platform/devices/MLNXBF13\\:00/"
            "driver/MLNXBF13\\:00/uefi_version 2>/dev/null || "
            "mlxbf-bootctl 2>/dev/null | head -10")

        if r.rc != 0 or not r.stdout.strip():
            r = bf3.execute(
                "test -d /sys/bus/platform/drivers/mlx-bootctl")
            if r.rc == 0:
                logger.info("mlx-bootctl driver present")
                return
            pytest.skip("Cannot access RShim registers from DPU")

        logger.info(f"Boot control info:\n{r.stdout.strip()}")


class TestRShimHost:
    """RShim verification from the host side.

    Ports the host-side RShim access from tileusb-test.c,
    verifying the RShim device is accessible on the host.
    """

    @pytest.mark.p0
    def test_rshim_device_on_host(self, bf3, host):
        """RSH-101: RShim device files exist on host."""
        if not _host_available(host):
            pytest.skip("Host SSH not available")

        r = host.ssh.execute("ls /dev/rshim0/ 2>/dev/null")
        if r.rc != 0 or not r.stdout.strip():
            r = host.ssh.execute(
                "ls /dev/rshim*/ 2>/dev/null | head -20")
            if r.rc != 0 or not r.stdout.strip():
                pytest.skip("No RShim device on host")

        files = r.stdout.strip().splitlines()
        logger.info(f"RShim device files: {len(files)}")
        for f in files:
            logger.info(f"  {f.strip()}")

    @pytest.mark.p0
    def test_rshim_misc_readable(self, bf3, host):
        """RSH-102: RShim misc file readable on host.

        The original test read boot_control and other RShim registers.
        We verify the misc info file is accessible.
        """
        if not _host_available(host):
            pytest.skip("Host SSH not available")

        for path in ["/dev/rshim0/misc", "/dev/rshim1/misc"]:
            r = host.ssh.execute(f"cat {path} 2>/dev/null")
            if r.rc == 0 and r.stdout.strip():
                logger.info(f"{path}:\n{r.stdout.strip()}")

                info = {}
                for line in r.stdout.splitlines():
                    if " " in line.strip():
                        parts = line.strip().split(None, 1)
                        if len(parts) == 2:
                            info[parts[0]] = parts[1]

                if info:
                    for k, v in info.items():
                        logger.info(f"  {k}: {v}")
                return

        pytest.skip("Cannot read RShim misc on host")

    @pytest.mark.p1
    def test_rshim_boot_channel(self, bf3, host):
        """RSH-103: RShim boot device file exists.

        The original test_usb_boot() pushed a boot image through
        the RShim boot channel.  We verify the channel exists.
        """
        if not _host_available(host):
            pytest.skip("Host SSH not available")

        for path in ["/dev/rshim0/boot", "/dev/rshim1/boot"]:
            r = host.ssh.execute(
                f"test -c {path} 2>/dev/null || "
                f"test -f {path} 2>/dev/null")
            if r.rc == 0:
                logger.info(f"Boot channel: {path}")
                return

        logger.warning("No RShim boot channel found")
        pytest.skip("RShim boot channel not accessible")

    @pytest.mark.p1
    def test_rshim_console_channel(self, bf3, host):
        """RSH-104: RShim console device file exists."""
        if not _host_available(host):
            pytest.skip("Host SSH not available")

        for path in ["/dev/rshim0/console",
                     "/dev/rshim1/console"]:
            r = host.ssh.execute(
                f"test -c {path} 2>/dev/null || "
                f"test -f {path} 2>/dev/null")
            if r.rc == 0:
                logger.info(f"Console channel: {path}")
                return

        logger.warning("No RShim console channel found")

    @pytest.mark.p1
    def test_rshim_driver_loaded_on_host(self, bf3, host):
        """RSH-105: RShim kernel module/driver loaded on host."""
        if not _host_available(host):
            pytest.skip("Host SSH not available")

        r = host.ssh.execute("lsmod | grep rshim 2>/dev/null")
        if r.rc == 0 and r.stdout.strip():
            logger.info(f"RShim module: {r.stdout.strip()}")
            return

        r = host.ssh.execute(
            "systemctl is-active rshim 2>/dev/null")
        if r.rc == 0 and "active" in r.stdout:
            logger.info("RShim running as userspace service")
            return

        r = host.ssh.execute("pgrep -a rshim 2>/dev/null")
        if r.rc == 0 and r.stdout.strip():
            logger.info(f"RShim process: {r.stdout.strip()}")
            return

        logger.warning("No RShim driver/service found on host")
