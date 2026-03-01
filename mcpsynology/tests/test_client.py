"""
Tests for SynologyClient — all HTTP calls are mocked with respx.
"""
from __future__ import annotations

import json
import pytest
import respx
import httpx

from synology_mcp.client import SynologyClient, SynologyAPIError
from synology_mcp.config import Settings

BASE_URL = "https://nas.test:5001/webapi/"

SETTINGS = Settings(
    synology_url="https://nas.test:5001",
    api_token="test-pat-token",
    ssl_verify=False,
    timeout=5.0,
)


def _dsm_ok(data: object) -> dict:
    return {"success": True, "data": data}


def _dsm_err(code: int) -> dict:
    return {"success": False, "error": {"code": code}}


# ---------------------------------------------------------------------------
# health_check / query_api_info
# ---------------------------------------------------------------------------

@respx.mock
@pytest.mark.asyncio
async def test_health_check_ok() -> None:
    respx.get(BASE_URL + "query.cgi").mock(
        return_value=httpx.Response(200, json=_dsm_ok({"SYNO.API.Info": {"path": "query.cgi"}}))
    )
    async with SynologyClient(SETTINGS) as client:
        data = await client.query_api_info()
    assert "SYNO.API.Info" in data


@respx.mock
@pytest.mark.asyncio
async def test_health_check_unauthorized() -> None:
    respx.get(BASE_URL + "query.cgi").mock(
        return_value=httpx.Response(401)
    )
    async with SynologyClient(SETTINGS) as client:
        with pytest.raises(SynologyAPIError) as exc_info:
            await client.query_api_info()
    assert exc_info.value.status_code == 401


@respx.mock
@pytest.mark.asyncio
async def test_dsm_application_error() -> None:
    """DSM returns HTTP 200 but success=false."""
    respx.get(BASE_URL + "query.cgi").mock(
        return_value=httpx.Response(200, json=_dsm_err(105))
    )
    async with SynologyClient(SETTINGS) as client:
        with pytest.raises(SynologyAPIError) as exc_info:
            await client.query_api_info()
    assert exc_info.value.error_code == 105
    assert "privilege" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# get_dsm_info
# ---------------------------------------------------------------------------

@respx.mock
@pytest.mark.asyncio
async def test_get_dsm_info() -> None:
    payload = {
        "model": "DS923+",
        "version": "7.2.2-72806",
        "firmware_ver": "7.2.2",
        "up_time": "10 days 2:30:00",
        "temperature": 35,
        "sys_temp_warn": False,
    }
    respx.get(BASE_URL + "entry.cgi").mock(
        return_value=httpx.Response(200, json=_dsm_ok(payload))
    )
    async with SynologyClient(SETTINGS) as client:
        data = await client.get_dsm_info()
    assert data["model"] == "DS923+"
    assert data["firmware_ver"] == "7.2.2"


# ---------------------------------------------------------------------------
# get_system_utilization
# ---------------------------------------------------------------------------

@respx.mock
@pytest.mark.asyncio
async def test_get_system_utilization() -> None:
    payload = {
        "cpu": {"user_load": 12, "system_load": 3, "other_load": 1},
        "memory": {"real_usage": 45, "total_real": 8192},
        "network": [{"device": "eth0", "rx": 1024, "tx": 512}],
        "disk": [{"device": "sda", "read_byte": 2048, "write_byte": 1024}],
    }
    respx.get(BASE_URL + "entry.cgi").mock(
        return_value=httpx.Response(200, json=_dsm_ok(payload))
    )
    async with SynologyClient(SETTINGS) as client:
        data = await client.get_system_utilization()
    assert data["cpu"]["user_load"] == 12


# ---------------------------------------------------------------------------
# list_shares
# ---------------------------------------------------------------------------

@respx.mock
@pytest.mark.asyncio
async def test_list_shares() -> None:
    payload = {
        "shares": [
            {"name": "docker", "vol_path": "/volume1/docker", "encrypted": False},
            {"name": "homes", "vol_path": "/volume1/homes", "encrypted": False},
        ],
        "total": 2,
    }
    respx.get(BASE_URL + "entry.cgi").mock(
        return_value=httpx.Response(200, json=_dsm_ok(payload))
    )
    async with SynologyClient(SETTINGS) as client:
        data = await client.list_shares()
    assert data["total"] == 2
    assert data["shares"][0]["name"] == "docker"


# ---------------------------------------------------------------------------
# list_docker_containers
# ---------------------------------------------------------------------------

@respx.mock
@pytest.mark.asyncio
async def test_list_docker_containers() -> None:
    payload = {
        "containers": [
            {"name": "portainer", "image": "portainer/portainer-ce:latest", "status": "running"},
            {"name": "grafana", "image": "grafana/grafana:latest", "status": "running"},
        ],
        "total": 2,
    }
    respx.get(BASE_URL + "entry.cgi").mock(
        return_value=httpx.Response(200, json=_dsm_ok(payload))
    )
    async with SynologyClient(SETTINGS) as client:
        data = await client.list_docker_containers()
    assert data["total"] == 2


# ---------------------------------------------------------------------------
# list_files
# ---------------------------------------------------------------------------

@respx.mock
@pytest.mark.asyncio
async def test_list_files() -> None:
    payload = {
        "files": [
            {"name": "compose.yml", "isdir": False, "path": "/docker/compose.yml"},
            {"name": "data", "isdir": True, "path": "/docker/data"},
        ],
        "total": 2,
    }
    respx.get(BASE_URL + "entry.cgi").mock(
        return_value=httpx.Response(200, json=_dsm_ok(payload))
    )
    async with SynologyClient(SETTINGS) as client:
        data = await client.list_files("/docker")
    assert data["total"] == 2
    assert data["files"][0]["name"] == "compose.yml"


# ---------------------------------------------------------------------------
# Context manager guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_client_without_context_manager_raises() -> None:
    client = SynologyClient(SETTINGS)
    with pytest.raises(RuntimeError, match="async context manager"):
        await client.query_api_info()
