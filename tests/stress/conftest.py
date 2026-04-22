# tests/stress/conftest.py

import pytest


def pytest_generate_tests(metafunc):
    """Dynamic parametrize for stress iteration count."""
    if "stress_iteration" in metafunc.fixturenames:
        count = metafunc.config.getoption("--stress-count")
        metafunc.parametrize("stress_iteration", range(count))

