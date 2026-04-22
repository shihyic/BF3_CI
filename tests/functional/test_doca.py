# tests/functional/test_doca.py

import pytest

pytestmark = [pytest.mark.functional, pytest.mark.doca]


class TestDOCA:
    """DOCA 2.x runtime validation."""

    @pytest.mark.p1
    def test_doca_version(self, bf3):
        """DOCA-001: DOCA runtime version."""
        version = bf3.get_doca_version()
        assert version != "unknown"

    @pytest.mark.p1
    def test_doca_flow(self, bf3):
        """DOCA-002: DOCA flow library available."""
        result = bf3.execute(
            "dpkg -l 2>/dev/null | grep doca-flow || "
            "rpm -q doca-flow 2>/dev/null"
        )
        assert result.rc == 0

    @pytest.mark.p2
    def test_ovs_offload_available(self, bf3):
        """DOCA-003: OVS hardware offload available."""
        result = bf3.execute(
            "ovs-vsctl get Open_vSwitch . "
            "other_config:hw-offload 2>/dev/null"
        )
        if result.rc != 0:
            pytest.skip("OVS not configured")
