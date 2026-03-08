"""
Pytest configuration for Wazuh deployment tests.
Registers custom marks so pytest does not warn about unknown marks.
"""
import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "offline: tests that run without any network or credentials")
    config.addinivalue_line("markers", "live: tests that require a live Portainer instance")
    config.addinivalue_line("markers", "deploy: tests that actually deploy/modify resources in Portainer")
    config.addinivalue_line("markers", "postdeploy: tests that run after a successful deployment")
    config.addinivalue_line("markers", "gateway: tests that require the mcp_http_gateway to be running")
