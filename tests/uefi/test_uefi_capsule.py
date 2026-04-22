# tests/uefi/test_uefi_capsule.py

import pytest

pytestmark = [pytest.mark.uefi, pytest.mark.destructive]


class TestUEFICapsule:
    """UEFI capsule update tests ? BF3 specific."""

    @pytest.mark.p0
    def test_get_uefi_version(self, bf3):
        """UEFI-001: Get current UEFI version."""
        version = bf3.get_uefi_version()
        assert version != "unknown"

    @pytest.mark.p1
    @pytest.mark.timeout(600)
    def test_uefi_capsule_update(self, bf3, bmc,
                                  uefi_capsule_path):
        """UEFI-002: Update UEFI via capsule."""
        if uefi_capsule_path is None:
            pytest.skip("No UEFI capsule specified")

        before = bf3.get_uefi_version()

        bf3.arm_ssh.scp_put(
            uefi_capsule_path, "/tmp/uefi-capsule.cap"
        )
        result = bf3.execute(
            "mlxbf-bootctl -c /tmp/uefi-capsule.cap"
        )
        assert result.rc == 0, (
            f"Capsule update failed: {result.stderr}"
        )

        # Reboot to apply
        bmc.host_power_cycle()
        assert bf3.wait_for_boot(timeout=300)

        after = bf3.get_uefi_version()
        assert after != "unknown"

    @pytest.mark.p0
    def test_boot_partition_info(self, bf3):
        """UEFI-003: Get boot partition info."""
        info = bf3.get_boot_partition()
        assert info
        assert "primary" in info.lower() or \
               "alternate" in info.lower()
