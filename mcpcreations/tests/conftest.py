"""
conftest.py for mcpcreations/tests/
Registers custom pytest marks for test_mcp_external.py and other tests.
"""
import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "gateway: tests requiring the mcp_http_gateway to be running")
    config.addinivalue_line("markers", "offline: no network or credentials required")
    config.addinivalue_line("markers", "live: requires live backend services")
