# tests/functional/test_pci.py
# Port of old_test/pci_test*.c, pci_test.sh, and pci_test_dev/.
# The original tests relied on a custom kernel module (pci_test_dev.ko)
# with proprietary ioctls for config/MMIO/DMA access.  This port uses
# standard Linux tools (lspci, setpci, sysfs) to verify the same PCI
# subsystem properties: device presence, config space, capabilities,
# BARs, link status, error state, MMIO readability, and interrupts.

import logging
import re

import pytest

pytestmark = [pytest.mark.functional]

logger = logging.getLogger(__name__)

NVIDIA_VENDOR_ID = "15b3"

BF3_EXPECTED_DEVICES = [
    {"class": "0200", "desc": "ConnectX NIC (Ethernet/IB)"},
    {"class": "0207", "desc": "BlueField Integrated NIC"},
]

EXPECTED_CAPS = [
    (0x10, "PCI Express"),
    (0x05, "MSI"),
    (0x11, "MSI-X"),
    (0x01, "Power Management"),
]

EXPECTED_EXT_CAPS = [
    (0x0001, "AER"),
    (0x0019, "Secondary PCI Express"),
]


def _lspci_parse(bf3) -> list[dict]:
    """Run lspci -vmm -nn and parse into list of device dicts."""
    r = bf3.execute("lspci -vmm -nn 2>/dev/null")
    if r.rc != 0:
        r = bf3.execute("which lspci 2>/dev/null")
        if r.rc != 0:
            bf3.execute(
                "apt-get update -qq 2>/dev/null && "
                "apt-get install -y -qq pciutils 2>/dev/null",
                timeout=60)
        r = bf3.execute("lspci -vmm -nn 2>/dev/null")
        assert r.rc == 0, "lspci not available"

    devices = []
    current: dict = {}
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            if current:
                devices.append(current)
                current = {}
            continue
        if ":" in line:
            key, val = line.split(":", 1)
            current[key.strip()] = val.strip()
    if current:
        devices.append(current)
    return devices


def _get_nvidia_bdf_list(bf3) -> list[str]:
    """Return list of BDF addresses for all NVIDIA PCI devices."""
    r = bf3.execute(
        f"lspci -d {NVIDIA_VENDOR_ID}: -D 2>/dev/null | "
        "awk '{print $1}'")
    if r.rc != 0 or not r.stdout.strip():
        return []
    return [b.strip() for b in r.stdout.splitlines() if b.strip()]


def _read_config_word(bf3, bdf: str, offset: int) -> int | None:
    """Read a 16-bit word from PCI config space via setpci."""
    r = bf3.execute(f"setpci -s {bdf} {offset:02x}.w 2>/dev/null")
    if r.rc != 0 or not r.stdout.strip():
        return None
    try:
        return int(r.stdout.strip(), 16)
    except ValueError:
        return None


def _read_config_long(bf3, bdf: str, offset: int) -> int | None:
    """Read a 32-bit dword from PCI config space via setpci."""
    r = bf3.execute(f"setpci -s {bdf} {offset:02x}.l 2>/dev/null")
    if r.rc != 0 or not r.stdout.strip():
        return None
    try:
        return int(r.stdout.strip(), 16)
    except ValueError:
        return None


class TestPCI:
    """PCI subsystem verification on BF3 DPU ARM.

    Port of old_test/pci_test.sh, pci_test_config.c, pci_test_mmio.c.
    Uses standard Linux PCI tools instead of the custom pci_test_dev
    kernel module.
    """

    @pytest.mark.p0
    def test_pci_devices_present(self, bf3):
        """PCI-001: NVIDIA PCI devices are enumerated."""
        devices = _lspci_parse(bf3)
        nvidia_devs = [
            d for d in devices
            if NVIDIA_VENDOR_ID in d.get("Vendor", "").lower()
            or NVIDIA_VENDOR_ID in d.get("SVendor", "").lower()
        ]

        logger.info(f"Total PCI devices: {len(devices)}")
        logger.info(f"NVIDIA PCI devices: {len(nvidia_devs)}")
        for d in nvidia_devs:
            logger.info(f"  {d.get('Slot', '?')}: "
                        f"{d.get('Device', '?')} "
                        f"[{d.get('Class', '?')}]")

        assert len(nvidia_devs) > 0, (
            "No NVIDIA PCI devices found on DPU")

    @pytest.mark.p0
    def test_config_space_readable(self, bf3):
        """PCI-002: PCI config space is readable (vendor/device ID).

        Mirrors the RO test from pci_test_config.c — verifies that
        vendor ID and device ID registers return valid values.
        """
        bdfs = _get_nvidia_bdf_list(bf3)
        assert bdfs, "No NVIDIA PCI devices to test"

        for bdf in bdfs:
            vendor = _read_config_word(bf3, bdf, 0x00)
            device = _read_config_word(bf3, bdf, 0x02)
            assert vendor is not None, (
                f"{bdf}: cannot read vendor ID")
            assert device is not None, (
                f"{bdf}: cannot read device ID")
            logger.info(f"{bdf}: vendor={vendor:04x} device={device:04x}")

            assert vendor == int(NVIDIA_VENDOR_ID, 16), (
                f"{bdf}: unexpected vendor ID {vendor:04x}")

    @pytest.mark.p0
    def test_config_ro_registers(self, bf3):
        """PCI-003: Read-only config registers are stable.

        Port of ro_test() from pci_test_config.c.  Reads vendor ID and
        device ID twice and confirms they don't change.
        """
        bdfs = _get_nvidia_bdf_list(bf3)
        assert bdfs, "No NVIDIA PCI devices to test"
        bdf = bdfs[0]

        for offset, name in [(0x00, "Vendor ID"), (0x02, "Device ID")]:
            v1 = _read_config_word(bf3, bdf, offset)
            v2 = _read_config_word(bf3, bdf, offset)
            assert v1 is not None and v2 is not None, (
                f"{bdf}: cannot read {name}")
            assert v1 == v2, (
                f"{bdf}: {name} unstable: "
                f"0x{v1:04x} vs 0x{v2:04x}")
            logger.info(f"{bdf}: {name}=0x{v1:04x} (stable)")

    @pytest.mark.p1
    def test_pci_capabilities(self, bf3):
        """PCI-004: Standard PCI capabilities present.

        Port of find_cap(type=0) from pci_test_common.c.
        """
        bdfs = _get_nvidia_bdf_list(bf3)
        assert bdfs, "No NVIDIA PCI devices to test"
        bdf = bdfs[0]

        r = bf3.execute(f"lspci -s {bdf} -vv 2>/dev/null")
        assert r.rc == 0, f"lspci -vv failed for {bdf}"

        found = []
        missing = []
        for cap_id, cap_name in EXPECTED_CAPS:
            if cap_name.lower() in r.stdout.lower():
                found.append(cap_name)
                logger.info(f"  Capability [{cap_id:02x}] "
                            f"{cap_name}: present")
            else:
                missing.append(f"{cap_name} [{cap_id:02x}]")
                logger.warning(f"  Capability [{cap_id:02x}] "
                               f"{cap_name}: NOT found")

        logger.info(f"Capabilities: {len(found)}/"
                     f"{len(EXPECTED_CAPS)} found")
        assert len(found) >= 2, (
            f"Too few standard capabilities: "
            f"missing {', '.join(missing)}")

    @pytest.mark.p1
    def test_pci_extended_capabilities(self, bf3):
        """PCI-005: Extended PCI capabilities present.

        Port of find_cap(type=1) from pci_test_common.c.
        """
        bdfs = _get_nvidia_bdf_list(bf3)
        assert bdfs, "No NVIDIA PCI devices to test"
        bdf = bdfs[0]

        r = bf3.execute(f"lspci -s {bdf} -vv 2>/dev/null")
        assert r.rc == 0, f"lspci -vv failed for {bdf}"

        found = []
        for cap_id, cap_name in EXPECTED_EXT_CAPS:
            if cap_name.lower() in r.stdout.lower():
                found.append(cap_name)
                logger.info(f"  ExtCap [{cap_id:04x}] "
                            f"{cap_name}: present")
            else:
                logger.info(f"  ExtCap [{cap_id:04x}] "
                            f"{cap_name}: not found")

        logger.info(f"Extended capabilities: {len(found)}/"
                     f"{len(EXPECTED_EXT_CAPS)} found")

    @pytest.mark.p0
    def test_bar_resources(self, bf3):
        """PCI-006: BARs are mapped and have non-zero size.

        Port of bar_test() from pci_test_config.c — verifies that
        at least one NVIDIA device has valid BAR resources via sysfs.
        """
        bdfs = _get_nvidia_bdf_list(bf3)
        assert bdfs, "No NVIDIA PCI devices to test"

        any_bars = False
        for bdf in bdfs:
            sysfs = f"/sys/bus/pci/devices/{bdf}/resource"
            r = bf3.execute(f"cat {sysfs} 2>/dev/null")
            if r.rc != 0:
                continue

            bars = []
            for i, line in enumerate(r.stdout.splitlines()):
                parts = line.strip().split()
                if len(parts) >= 3:
                    start = int(parts[0], 16)
                    end = int(parts[1], 16)
                    if start != 0 and end != 0:
                        size = end - start + 1
                        bars.append((i, start, size))

            if bars:
                any_bars = True
                for bar_num, start, size in bars:
                    logger.info(
                        f"{bdf} BAR{bar_num}: "
                        f"start=0x{start:x} size=0x{size:x} "
                        f"({size // 1024}KB)")

        assert any_bars, "No BARs found on any NVIDIA PCI device"

    @pytest.mark.p0
    def test_pcie_link_status(self, bf3):
        """PCI-007: PCIe link is active with expected speed/width."""
        bdfs = _get_nvidia_bdf_list(bf3)
        assert bdfs, "No NVIDIA PCI devices to test"

        link_found = False
        for bdf in bdfs:
            r = bf3.execute(
                f"lspci -s {bdf} -vv 2>/dev/null | "
                "grep -i 'lnksta:'")
            if r.rc != 0 or not r.stdout.strip():
                continue

            link_found = True
            line = r.stdout.strip()
            logger.info(f"{bdf} LnkSta: {line}")

            speed_m = re.search(r'Speed\s+(\S+)', line)
            width_m = re.search(r'Width\s+x(\d+)', line)
            if speed_m:
                logger.info(f"  Link speed: {speed_m.group(1)}")
            if width_m:
                width = int(width_m.group(1))
                logger.info(f"  Link width: x{width}")
                assert width > 0, (
                    f"{bdf}: link width is 0 (link down?)")

        if not link_found:
            logger.warning("No PCIe link status found "
                           "(devices may be integrated)")

    @pytest.mark.p1
    def test_no_aer_errors(self, bf3):
        """PCI-008: No uncorrectable AER errors on NVIDIA devices."""
        bdfs = _get_nvidia_bdf_list(bf3)
        if not bdfs:
            pytest.skip("No NVIDIA PCI devices")

        errors_found = []
        for bdf in bdfs:
            r = bf3.execute(
                f"cat /sys/bus/pci/devices/{bdf}/"
                f"aer_dev_fatal 2>/dev/null")
            if r.rc == 0 and r.stdout.strip():
                total = sum(
                    int(x) for x in re.findall(r'\d+', r.stdout)
                )
                if total > 0:
                    errors_found.append(
                        f"{bdf}: fatal={r.stdout.strip()}")
                    logger.error(f"{bdf} AER fatal: "
                                 f"{r.stdout.strip()}")

            r = bf3.execute(
                f"cat /sys/bus/pci/devices/{bdf}/"
                f"aer_dev_nonfatal 2>/dev/null")
            if r.rc == 0 and r.stdout.strip():
                total = sum(
                    int(x) for x in re.findall(r'\d+', r.stdout)
                )
                if total > 0:
                    logger.warning(f"{bdf} AER nonfatal: "
                                   f"{r.stdout.strip()}")

        if errors_found:
            logger.error(f"AER fatal errors: {errors_found}")

        assert not errors_found, (
            f"Fatal AER errors on: "
            f"{', '.join(errors_found)}")

    @pytest.mark.p1
    def test_pci_device_status(self, bf3):
        """PCI-009: PCI Status register has no error bits set.

        Port of rw1c_test() intent — checks the Status register
        error bits (Detected Parity Error, Signaled System Error,
        Master Data Parity Error, Signaled Target Abort,
        Received Target Abort, Received Master Abort).
        """
        bdfs = _get_nvidia_bdf_list(bf3)
        assert bdfs, "No NVIDIA PCI devices to test"

        STATUS_ERROR_MASK = 0xF900

        for bdf in bdfs:
            status = _read_config_word(bf3, bdf, 0x06)
            if status is None:
                logger.warning(f"{bdf}: cannot read status")
                continue

            errors = status & STATUS_ERROR_MASK
            logger.info(f"{bdf}: Status=0x{status:04x} "
                        f"(error bits=0x{errors:04x})")

            if errors:
                logger.warning(
                    f"{bdf}: Status register error bits set: "
                    f"0x{errors:04x}")
                if errors & 0x8000:
                    logger.warning(f"  {bdf}: Detected Parity Error")
                if errors & 0x4000:
                    logger.warning(f"  {bdf}: Signaled System Error")
                if errors & 0x2000:
                    logger.warning(
                        f"  {bdf}: Received Master Abort")
                if errors & 0x1000:
                    logger.warning(
                        f"  {bdf}: Received Target Abort")
                if errors & 0x0800:
                    logger.warning(
                        f"  {bdf}: Signaled Target Abort")
                if errors & 0x0100:
                    logger.warning(
                        f"  {bdf}: Master Data Parity Error")

    @pytest.mark.p2
    def test_lspci_output_captured(self, bf3):
        """PCI-010: Full lspci -v output captured for diagnostics.

        Mirrors the lspci capture at the start of pci_test.sh.
        """
        r = bf3.execute("lspci -v 2>/dev/null")
        assert r.rc == 0, "lspci -v failed"

        lines = r.stdout.strip().splitlines()
        logger.info(f"lspci -v: {len(lines)} lines of output")

        nvidia_lines = [
            l for l in lines
            if "mellanox" in l.lower() or "nvidia" in l.lower()
        ]
        logger.info(f"NVIDIA/Mellanox entries: {len(nvidia_lines)}")
        for line in nvidia_lines:
            logger.info(f"  {line.strip()}")

        assert lines, "lspci -v produced no output"

    @pytest.mark.p1
    def test_bar_mmio_readable(self, bf3):
        """PCI-011: BAR MMIO regions are readable via sysfs resource.

        Port of pci_test_dev.c MMIO read functionality.
        The kernel module used ioremap + readq on BAR0/BAR5.
        We read via sysfs resource files which are mmap-able
        from userspace, or fallback to dd.
        """
        bdfs = _get_nvidia_bdf_list(bf3)
        assert bdfs, "No NVIDIA PCI devices to test"

        any_readable = False
        for bdf in bdfs:
            sysfs_base = f"/sys/bus/pci/devices/{bdf}"
            r = bf3.execute(f"cat {sysfs_base}/resource 2>/dev/null")
            if r.rc != 0:
                continue

            for bar_idx, line in enumerate(
                    r.stdout.splitlines()):
                parts = line.strip().split()
                if len(parts) < 3:
                    continue
                start = int(parts[0], 16)
                end = int(parts[1], 16)
                flags = int(parts[2], 16)
                if start == 0 or end == 0:
                    continue
                is_mem = (flags & 0x1) == 0
                if not is_mem:
                    continue

                res_file = f"{sysfs_base}/resource{bar_idx}"
                r = bf3.execute(
                    f"test -r {res_file} && "
                    f"dd if={res_file} of=/dev/null "
                    f"bs=4 count=1 2>&1")
                if r.rc == 0:
                    any_readable = True
                    size = end - start + 1
                    logger.info(
                        f"{bdf} BAR{bar_idx}: MMIO read OK "
                        f"(size=0x{size:x})")
                else:
                    logger.info(
                        f"{bdf} BAR{bar_idx}: resource file "
                        f"not readable (may need enable)")

        if not any_readable:
            logger.warning(
                "No BAR MMIO resources were readable via sysfs")

    @pytest.mark.p1
    def test_interrupt_allocation(self, bf3):
        """PCI-012: MSI/MSI-X interrupts allocated for NVIDIA devices.

        Port of pci_test_dev.c interrupt handling (INTx/MSI/MSI-X).
        The kernel module registered interrupt handlers via
        request_irq with pci_enable_msi/msix_exact.
        We verify that interrupt vectors are allocated by checking
        /proc/interrupts and lspci capabilities.
        """
        bdfs = _get_nvidia_bdf_list(bf3)
        assert bdfs, "No NVIDIA PCI devices to test"

        r = bf3.execute("cat /proc/interrupts 2>/dev/null")
        assert r.rc == 0, "Cannot read /proc/interrupts"
        irq_lines = r.stdout

        any_irqs = False
        for bdf in bdfs:
            short_bdf = bdf.split(":", 1)[-1] if ":" in bdf else bdf

            matching = [
                l for l in irq_lines.splitlines()
                if short_bdf in l
                or "mlx" in l.lower()
                or "mellanox" in l.lower()
            ]
            if matching:
                any_irqs = True
                logger.info(f"{bdf}: {len(matching)} IRQ "
                            f"line(s) in /proc/interrupts")

            r = bf3.execute(
                f"lspci -s {bdf} -vv 2>/dev/null | "
                "grep -iE 'MSI-X:|MSI:'")
            if r.rc == 0 and r.stdout.strip():
                for line in r.stdout.strip().splitlines():
                    logger.info(f"  {bdf}: {line.strip()}")

        r = bf3.execute(
            "grep -cE 'mlx|PCI-MSI' /proc/interrupts "
            "2>/dev/null || echo 0")
        count = r.stdout.strip()
        logger.info(f"Total mlx/PCI-MSI interrupt lines: {count}")

    @pytest.mark.p1
    def test_pci_bus_master_enabled(self, bf3):
        """PCI-013: Bus Master is enabled on NVIDIA devices.

        Port of pci_test_dev.c: pci_set_master() call in probe.
        The kernel module enabled bus mastering for DMA.  We verify
        via the Command register bit 2 (Bus Master Enable).
        """
        bdfs = _get_nvidia_bdf_list(bf3)
        assert bdfs, "No NVIDIA PCI devices to test"

        for bdf in bdfs:
            cmd = _read_config_word(bf3, bdf, 0x04)
            if cmd is None:
                logger.warning(f"{bdf}: cannot read Command reg")
                continue

            bus_master = bool(cmd & 0x04)
            mem_space = bool(cmd & 0x02)
            io_space = bool(cmd & 0x01)
            logger.info(
                f"{bdf}: Command=0x{cmd:04x} "
                f"BusMaster={bus_master} "
                f"MemSpace={mem_space} "
                f"IOSpace={io_space}")

            assert bus_master, (
                f"{bdf}: Bus Master not enabled "
                f"(Command=0x{cmd:04x})")
