# tests/bmc/test_bmc_firmware.py

import pytest

pytestmark = [pytest.mark.bmc]


class TestBMCFirmware:
    """BMC firmware update and verification."""

    @pytest.mark.p0
    def test_get_bmc_firmware_version(self, bmc):
        """BMC-002: Get BMC firmware version."""
        version = bmc.get_firmware_version()
        assert version != "unknown"
        assert len(version) > 0

    @pytest.mark.p0
    @pytest.mark.destructive
    @pytest.mark.timeout(900)
    def test_update_bmc_firmware_scp(self, bmc, bmc_fw_path):
        """BMC-001a: Update BMC firmware via SCP."""
        if bmc_fw_path is None:
            pytest.skip("No BMC firmware specified")

        assert bmc.update_firmware_scp(bmc_fw_path)
        bmc.reboot()
        assert bmc.wait_for_ready(timeout=300)

    @pytest.mark.p1
    @pytest.mark.destructive
    @pytest.mark.timeout(900)
    def test_update_bmc_firmware_redfish(self, bmc,
                                          bmc_fw_path):
        """BMC-001b: Update BMC firmware via Redfish."""
        if bmc_fw_path is None:
            pytest.skip("No BMC firmware specified")

        assert bmc.update_firmware_redfish(bmc_fw_path)
        assert bmc.wait_for_ready(timeout=300)
