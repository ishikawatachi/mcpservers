"""Tests for the Portainer API client (mocked HTTP layer)."""
from __future__ import annotations

from typing import Any
import json
import pytest
import httpx
import respx

from portainer_mcp.client import PortainerClient, PortainerAPIError
from portainer_mcp.config import Settings

BASE = "https://portainer.test"


def _settings(**kwargs: Any) -> Settings:
    return Settings(
        portainer_url=BASE,
        api_token=kwargs.get("api_token", "ptr_test_token"),
        ssl_verify=False,
        timeout=5.0,
    )


# ---------------------------------------------------------------------------
# Auth header selection
# ---------------------------------------------------------------------------

class TestAuthHeaders:
    @pytest.mark.asyncio
    async def test_ptr_token_uses_x_api_key(self):
        settings = _settings(api_token="ptr_some_token")
        async with PortainerClient(settings) as client:
            assert "X-API-Key" in client._headers
            assert "Authorization" not in client._headers

    @pytest.mark.asyncio
    async def test_jwt_uses_bearer(self):
        settings = _settings(api_token="eyJhbGciOiJIUzI1NiJ9.test.signature")
        async with PortainerClient(settings) as client:
            assert client._headers.get("Authorization", "").startswith("Bearer ")


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

class TestHealth:
    @respx.mock
    @pytest.mark.asyncio
    async def test_health_ok(self):
        respx.get(f"{BASE}/api/status").mock(
            return_value=httpx.Response(200, json={"Version": "2.21.0"})
        )
        async with PortainerClient(_settings()) as client:
            result = await client.health()
        assert result["Version"] == "2.21.0"


# ---------------------------------------------------------------------------
# list_containers
# ---------------------------------------------------------------------------

class TestListContainers:
    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_containers(self):
        respx.get(f"{BASE}/api/endpoints/1/docker/containers/json").mock(
            return_value=httpx.Response(200, json=[{"Id": "abc123", "Names": ["/web"], "State": "running"}])
        )
        async with PortainerClient(_settings()) as client:
            result = await client.list_containers(1)
        assert result[0]["Id"] == "abc123"

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_on_401(self):
        respx.get(f"{BASE}/api/endpoints/1/docker/containers/json").mock(
            return_value=httpx.Response(401, json={"message": "Unauthorized"})
        )
        async with PortainerClient(_settings()) as client:
            with pytest.raises(PortainerAPIError) as exc_info:
                await client.list_containers(1)
        assert exc_info.value.status_code == 401

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_on_404(self):
        respx.get(f"{BASE}/api/endpoints/99/docker/containers/json").mock(
            return_value=httpx.Response(404)
        )
        async with PortainerClient(_settings()) as client:
            with pytest.raises(PortainerAPIError) as exc_info:
                await client.list_containers(99)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# stop / start container
# ---------------------------------------------------------------------------

class TestContainerLifecycle:
    @respx.mock
    @pytest.mark.asyncio
    async def test_stop_container(self):
        respx.post(f"{BASE}/api/endpoints/1/docker/containers/abc/stop").mock(
            return_value=httpx.Response(204)
        )
        async with PortainerClient(_settings()) as client:
            await client.stop_container(1, "abc")  # should not raise

    @respx.mock
    @pytest.mark.asyncio
    async def test_start_container(self):
        respx.post(f"{BASE}/api/endpoints/1/docker/containers/abc/start").mock(
            return_value=httpx.Response(204)
        )
        async with PortainerClient(_settings()) as client:
            await client.start_container(1, "abc")  # should not raise


# ---------------------------------------------------------------------------
# list_stacks
# ---------------------------------------------------------------------------

class TestListStacks:
    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_stacks(self):
        respx.get(f"{BASE}/api/stacks").mock(
            return_value=httpx.Response(200, json=[{"Id": 1, "Name": "mystack", "EndpointId": 1, "Status": 1}])
        )
        async with PortainerClient(_settings()) as client:
            stacks = await client.list_stacks()
        assert stacks[0]["Name"] == "mystack"
