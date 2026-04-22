# BF3 DPU CI Test Framework

A pytest-based test framework for BlueField-3 DPU hardware CI validation.
Tests run from a Linux host and execute commands on the DPU ARM, BMC, and
host server over SSH and Redfish.

## Prerequisites

| Requirement | Minimum Version |
|-------------|-----------------|
| Python      | 3.10+           |
| pip         | 21.0+           |
| SSH access  | To DPU ARM, BMC, and host server |
| Network     | Host machine must reach all three targets |

The test runner machine (where pytest executes) does **not** need to be the
host server — it only needs network connectivity to the DPU ARM, BMC, and
host IPs listed in the testbed config.

## Installation

### 1. Create a Python virtual environment

```bash
python3 -m venv /path/to/venv
source /path/to/venv/bin/activate
```

### 2. Clone and install the framework

```bash
git clone <repo-url> bf3-ci-tests
cd bf3-ci-tests
pip install -e .
```

This installs the `bf3_ci` package in editable mode along with all
dependencies (paramiko, pytest, pytest-html, pyyaml, etc.).

### 3. Verify installation

```bash
pytest --co -q
```

This should list all collected tests without running them. If you see
`ModuleNotFoundError: No module named 'bf3_ci'`, re-run `pip install -e .`

## Project Structure

```
bf3-ci-tests/
├── pyproject.toml              # Package metadata and dependencies
├── pytest.ini                  # Pytest configuration and markers
├── conftest.py                 # CLI options, session fixtures, timeouts
├── README.md                   # This file
│
├── bf3_ci/                     # Core framework package
│   ├── devices/
│   │   ├── bf3_device.py       # DPU ARM interaction (SSH)
│   │   ├── bmc_device.py       # BMC interaction (Redfish + SSH)
│   │   ├── host_device.py      # Host server interaction (SSH)
│   │   └── rshim_device.py     # RShim device abstraction
│   ├── lib/
│   │   └── health_check.py     # Device health verification
│   ├── plugins/
│   │   ├── pytest_bf3_report.py    # HTML report customization
│   │   └── pytest_bf3_recovery.py  # Auto-recovery on failure
│   └── transport/
│       ├── ssh.py              # Paramiko SSH wrapper
│       └── redfish.py          # Redfish REST client
│
├── config/                     # Testbed configuration files
│   └── testbed.sample.yaml     # Example layout (copy & edit; keep secrets local)
│
├── tests/                      # Test suites
│   ├── conftest.py             # Device fixtures (bf3, bmc, host)
│   ├── preflight/
│   │   └── test_preflight.py   # Connectivity checks
│   ├── bfb/
│   │   └── test_bfb_install.py # BFB installation and verification
│   ├── functional/             # Hardware functional tests
│   │   ├── test_bootctl.py     # Boot control and sysfs API
│   │   ├── test_drivers.py     # Kernel modules and drivers
│   │   ├── test_eeprom.py      # I2C EEPROM verification
│   │   ├── test_gpio.py        # GPIO pin testing
│   │   ├── test_memtest.py     # Memory integrity
│   │   ├── test_pci.py         # PCI subsystem verification
│   │   ├── test_rshim.py       # RShim and TMFIFO
│   │   ├── test_storage.py     # Storage and partitions
│   │   ├── test_write_device.py # Device write/read verification
│   │   ├── test_doca.py        # DOCA runtime tests
│   │   ├── test_emmc.py        # eMMC health tests
│   │   └── test_network.py     # Network interface tests
│   ├── bmc/
│   │   ├── conftest.py         # BMC-specific fixtures
│   │   ├── test_bmc_firmware.py
│   │   ├── test_bmc_power.py
│   │   └── test_bmc_rshim.py
│   ├── uefi/
│   │   └── test_uefi_capsule.py
│   └── stress/
│       ├── conftest.py         # Stress iteration parametrize
│       ├── test_reboot_stress.py
│       └── test_rshim_stress.py
│
├── results/                    # Test output (generated)
│   ├── junit.xml
│   ├── report.html
│   └── test.log
│
└── old_test/                   # Legacy C/shell tests (reference only)
```

## Testbed Configuration

Each physical testbed uses a YAML file (often outside Git). Create one by
copying the sample and filling in your lab’s addresses and credentials:

```bash
cp config/testbed.sample.yaml config/testbed.yaml
```

Edit the file with your lab's IP addresses and credentials:

```yaml
testbed:
  name: "bf3-ci-testbed-mylab"
  description: "My BF3 DPU test environment"

  dut:
    - name: "my-dpu-host"
      type: "BlueField-3-DK"           # or BlueField-3-QP
      part_number: "900-9D3B4-00EN-E"

      arm:                              # DPU ARM (runs on the BF3)
        ip: "10.x.x.x"                 # DPU ARM OOB management IP
        user: "root"
        password: "<arm-root-password>"
        default_user: "<bfb-first-boot-user>"
        default_password: "<bfb-first-boot-password>"

      bmc:                              # BMC (manages the DPU)
        ip: "10.x.x.x"
        user: "root"
        password: "<bmc-password>"
        redfish_base: "https://10.x.x.x/redfish/v1"

      host:                             # Host server (DPU is plugged into)
        ip: "10.x.x.x"
        user: "root"
        password: "<host-password>"
        rshim_device: "/dev/rshim0"     # or /dev/rshim1
        pci_address: "00:00.0"          # DPU's PCIe BDF on the host (example)

      network:
        oob_interface: "oob_net0"
        data_interfaces: ["p0", "p1"]   # p1 is optional for single-port
        tmfifo_ip: "192.168.100.2"
        port_speed: "200GbE"

      emmc:
        device: "/dev/mmcblk0"

  artifacts:
    bfb_dir: "/artifacts/bfb/"
    fw_dir: "/artifacts/firmware/"
    capsule_dir: "/artifacts/capsules/"

  timeouts:
    ssh_connect: 30
    bfb_complete: 2400                  # BFB install timeout (40 min)
    boot_wait: 600                      # Post-reboot wait (10 min)
    rshim_enable: 120
    bmc_reboot: 300
    default: 300
```

### Required fields

| Section | Field | Description |
|---------|-------|-------------|
| `arm`   | `ip`, `user`, `password` | SSH access to BF3 DPU ARM core |
| `bmc`   | `ip`, `user`, `password`, `redfish_base` | BMC Redfish and SSH access |
| `host`  | `ip`, `user`, `password`, `rshim_device` | Host server with RShim |

### Optional sections

| Section | Purpose |
|---------|---------|
| `gpio`  | Override GPIO chip name and pin selection |
| `emmc`  | eMMC device path (defaults to `/dev/mmcblk0`) |
| `timeouts` | Override any default timeout value |

## Running Tests

### Basic usage

```bash
# Run all tests against a specific testbed
pytest --testbed config/testbed.yaml

# Run with verbose output
pytest --testbed config/testbed.yaml -v
```

### Run specific test suites

```bash
# Functional tests only
pytest --testbed config/testbed.yaml tests/functional/ -v

# Single test file
pytest --testbed config/testbed.yaml tests/functional/test_pci.py -v

# Single test class or method
pytest --testbed config/testbed.yaml tests/functional/test_pci.py::TestPCI::test_pci_devices_present -v
```

### Run by marker / priority

```bash
# Only P0 (must-pass) tests
pytest --testbed config/testbed.yaml -m p0 -v

# Only P0 and P1 tests
pytest --testbed config/testbed.yaml -m "p0 or p1" -v

# Functional tests, skip destructive
pytest --testbed config/testbed.yaml -m "functional and not destructive" -v

# Only preflight connectivity checks
pytest --testbed config/testbed.yaml -m preflight -v

# Stress tests with custom iteration count
pytest --testbed config/testbed.yaml tests/stress/ --stress-count 50 -v
```

### Available markers

| Marker | Description |
|--------|-------------|
| `preflight` | Connectivity and reachability checks |
| `bfb` | BFB installation and boot tests |
| `functional` | Hardware functional validation |
| `bmc` | BMC firmware and management |
| `uefi` | UEFI capsule and boot |
| `stress` | Stress and endurance tests |
| `doca` | DOCA runtime tests |
| `emmc` | eMMC storage tests |
| `p0` | Priority 0 — must pass |
| `p1` | Priority 1 — should pass |
| `p2` | Priority 2 — nice to pass |
| `destructive` | May alter device state (partition swaps, boot config writes) |
| `slow` | Takes longer than 5 minutes |

### CLI options

| Option | Default | Description |
|--------|---------|-------------|
| `--testbed` | `config/testbed.yaml` | Path to testbed YAML |
| `--bfb` | None | Path to BFB file for installation tests |
| `--bmc-fw` | None | Path to BMC firmware image |
| `--nic-fw` | None | Path to NIC firmware image |
| `--uefi-capsule` | None | Path to UEFI capsule file |
| `--skip-install` | False | Skip BFB installation step |
| `--rshim-mode` | `auto` | RShim source: `host`, `bmc`, or `auto` |
| `--recovery-mode` | `auto` | Recovery on failure: `auto`, `manual`, `skip` |
| `--stress-count` | 100 | Number of iterations for stress tests |
| `--bf-cfg` | None | Path to bf.cfg for BFB install customization |

### BFB installation workflow

```bash
# Install a BFB and run full validation
pytest --testbed config/testbed.yaml \
       --bfb /path/to/bf3-image.bfb \
       tests/bfb/ tests/functional/ -v

# Skip installation, test an already-running DPU
pytest --testbed config/testbed.yaml \
       --skip-install \
       tests/functional/ -v
```

## Test Output

Results are written to the `results/` directory:

| File | Format | Description |
|------|--------|-------------|
| `results/report.html` | HTML | Interactive report (open in browser) |
| `results/junit.xml` | JUnit XML | CI system integration (Jenkins, GitLab) |
| `results/test.log` | Plain text | Full debug-level log |

Console output shows live progress with `INFO`-level logging. The log file
captures `DEBUG`-level detail including full SSH command output.

## Functional Test Reference

| Test File | Tests | What It Verifies |
|-----------|-------|------------------|
| `test_bootctl.py` | 17 | Boot control info, partition swap, sysfs API (reset_action, second_reset_action, post_reset_wdog, breadcrumb0 integrity), watchdog-swap |
| `test_drivers.py` | 7 | Essential kernel modules (mlxbf_gige, mlx5_core, etc.), OOB interface, ethtool info, kernel taint |
| `test_eeprom.py` | 4 | I2C EEPROM discovery, sysfs/i2c-tools read, write/verify cycle |
| `test_gpio.py` | 6 | GPIO controller discovery, libgpiod line info, pin read/write |
| `test_memtest.py` | 5 | memtester availability, small/medium/large memory tests, ECC status |
| `test_pci.py` | 13 | PCI device enumeration, config space, capabilities, BARs, link status, AER errors, MMIO, interrupts, bus master |
| `test_rshim.py` | 11 | TMFIFO module, tmfifo_net0, console device, CoreSight, USB, host-side RShim files and driver status |
| `test_storage.py` | 8 | Root filesystem, partitions, eMMC device/health, writability, disk space |
| `test_write_device.py` | 6 | Random and linear write/read verification, block device reads |

## DPU Software Dependencies

Some tests install utilities on the DPU ARM via `apt-get` if missing:

| Utility | Used By | Package |
|---------|---------|---------|
| `memtester` | test_memtest.py | `memtester` |
| `ethtool` | test_drivers.py | `ethtool` |
| `i2c-tools` | test_eeprom.py | `i2c-tools` |
| `libgpiod-utils` | test_gpio.py | `libgpiod-utils` or `gpiod` |
| `lspci` / `setpci` | test_pci.py | `pciutils` |

The DPU ARM needs internet access (or a local apt mirror) for auto-install
to work. If the DPU has no network access, pre-install these packages in
the BFB image.

## Troubleshooting

### "BMC is not reachable" — tests skip

The `check_device_alive` fixture runs before every test. Verify BMC
connectivity:

```bash
curl -k https://<bmc-ip>/redfish/v1/
```

### "BF3 ARM is not reachable" — tests skip

SSH to the DPU ARM must work:

```bash
ssh root@<arm-ip>
```

If the DPU was recently re-imaged, use the first-boot SSH user and
password defined by your BFB image (see that image’s release notes);
many images require a password change on first login. Run the BFB
install tests first (`tests/bfb/`) when you need the framework to
establish persistent root access after install.

### SSH host key mismatch

After re-imaging, the DPU ARM generates new SSH host keys. Clear old
entries:

```bash
ssh-keygen -R <arm-ip>
```

### Tests skip with "... not found"

Some tests skip gracefully when hardware or sysfs interfaces are not
available on the specific DPU variant. For example:
- GPIO tests skip if `MLNXBF33` GPIO controller doesn't support chardev ops
- EEPROM tests skip if no user-accessible EEPROM is found (IPMI/IPMB only)
- Bootctl sysfs tests skip if `MLNXBF04` platform device attributes are missing

These skips are expected and not failures.

### Timeout errors

Increase timeouts in the testbed YAML or on the command line:

```bash
pytest --testbed config/testbed.yaml --timeout=1200 -v
```

## Adding a New Testbed

1. Copy the sample: `cp config/testbed.sample.yaml config/testbed-new.yaml`
2. Update all IP addresses, credentials, and hardware details
3. Run preflight checks: `pytest --testbed config/testbed-new.yaml -m preflight -v`
4. Run functional tests: `pytest --testbed config/testbed-new.yaml tests/functional/ -v`
