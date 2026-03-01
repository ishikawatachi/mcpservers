"""
Tests for SynologyClient — all HTTP calls are mocked with respx.

Auth flow (SYNO.API.Auth session-based):
  Every test sequences three calls on entry.cgi:
    1. login  → {"success": true, "data": {"sid": "test-sid"}}
    2. actual API call (or query.cgi for query_api_info)
    3. logout → {"success": true}
"""
from __future__ import annotations

import pytest
import respx
import httpx

from synology_mcp.client import SynologyClient, SynologyAPIError
from synology_mcp.config import Settings

BASE_URL = "https://nas.test:5001/webapi/"

SETTINGS = Settings(
    synology_url="https://nas.test:5001",
    username="admin",
    password="secret",
    ssl_verify=False,
    timeout=5.0,
)

# Shared mock responses for login/logout
_LOGIN = httpx.Response(200, json={"success": True, "data": {"sid": "test-sid"}})
_LOGOUT = httpx.Response(200, json={"success": True})


def _dsm_ok(data: object) -> dict:
    return {"success": True, "data": data}


def _dsm_err(code: int) -> dict:
    return {"success": False, "error": {"code": code}}


# ---------------------------------------------------------------------------
# health_check / query_api_info  (hits query.cgi; login/logout on entry.cgi)
# ---------------------------------------------------------------------------

@respx.mock
@pytest.mark.asyncio
async def test_health_check_ok() -> None:
    respx.get(BASE_URL + "entry.cgi").mock(side_effect=[_LOGIN, _LOGOUT])
    respx.get(BASE_URL + "query.cgi").mock(
        return_value=httpx.Response(200, json=_dsm_ok({"SYNO.API.Info": {"path": "query.cgi"}}))
    )
    async with SynologyClient(SETTINGS) as client:
        data = await client.query_api_info()
    assert "SYNO.API.Info" in data


@respx.mock
@pytest.mark.asyncio
async def test_health_check_unauthorized() -> None:
    respx.get(BASE_URL + "entry.cgi").mock(side_effect=[_LOGIN, _LOGOUT])
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
    respx.get(BASE_URL + "entry.cgi").mock(side_effect=[_LOGIN, _LOGOUT])
    respx.get(BASE_URL + "query.cgi").mock(
        return_value=httpx.Response(200, json=_dsm_err(105))
    )
    async with SynologyClient(SETTINGS) as client:
        with pytest.raises(SynologyAPIError) as exc_info:
            await client.query_api_info()
    assert exc_info.value.error_code == 105
    assert "privilege" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Login failure paths
# ---------------------------------------------------------------------------

@respx.mock
@pytest.mark.asyncio
async def test_login_bad_credentials() -> None:
    """DSM returns success=false on login (wrong password)."""
    respx.get(BASE_URL + "entry.cgi").mock(
        return_value=httpx.Response(200, json={"success": False, "error": {"code": 400}})
    )
    with pytest.raises(SynologyAPIError) as exc_info:
        async with SynologyClient(SETTINGS):
            pass
    assert exc_info.value.error_code == 400
    assert "password" in str(exc_info.value).lower()


@respx.mock
@pytest.mark.asyncio
async def test_login_http_error() -> None:
    """Non-2xx HTTP response from the login endpoint."""
    respx.get(BASE_URL + "entry.cgi").mock(
        return_value=httpx.Response(503)
    )
    with pytest.raises(SynologyAPIError) as exc_info:
        async with SynologyClient(SETTINGS):
            pass
    assert exc_info.value.status_code == 503


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
        side_effect=[_LOGIN, httpx.Response(200, json=_dsm_ok(payload)), _LOGOUT]
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
        side_effect=[_LOGIN, httpx.Response(200, json=_dsm_ok(payload)), _LOGOUT]
    )
    async with SynologyClient(SETTINGS) as client:
        data = await client.get_system_utilization()
    assert data["cpu"]["user_load"] == 12


# ---------------------------------------------------------------------------
# get_storage_info (SYNO.Storage.CGI.Storage — confirmed on entry.cgi)
# ---------------------------------------------------------------------------

@respx.mock
@pytest.mark.asyncio
async def test_get_storage_info() -> None:
    payload = {
        "volumes": [
            {
                "id": "volume_1",
                "status": "normal",
                "size_total_byte": "7999999999",
                "size_used_byte": "3000000000",
            }
        ],
        "disk": [],
    }
    respx.get(BASE_URL + "entry.cgi").mock(
        side_effect=[_LOGIN, httpx.Response(200, json=_dsm_ok(payload)), _LOGOUT]
    )
    async with SynologyClient(SETTINGS) as client:
        data = await client.get_storage_info()
    assert data["volumes"][0]["id"] == "volume_1"


# ---------------------------------------------------------------------------
# get_disk_info (SYNO.Storage.CGI.HddMan — confirmed on entry.cgi)
# ---------------------------------------------------------------------------

@respx.mock
@pytest.mark.asyncio
async def test_get_disk_info() -> None:
    payload = {
        "disk": [
            {"id": "disk1", "model": "WD Red Plus 8TB", "status": "normal", "temp": 38},
            {"id": "disk2", "model": "WD Red Plus 8TB", "status": "normal", "temp": 37},
        ]
    }
    respx.get(BASE_URL + "entry.cgi").mock(
        side_effect=[_LOGIN, httpx.Response(200, json=_dsm_ok(payload)), _LOGOUT]
    )
    async with SynologyClient(SETTINGS) as client:
        data = await client.get_disk_info()
    assert len(data["disk"]) == 2
    assert data["disk"][0]["temp"] == 38


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
        side_effect=[_LOGIN, httpx.Response(200, json=_dsm_ok(payload)), _LOGOUT]
    )
    async with SynologyClient(SETTINGS) as client:
        data = await client.list_shares()
    assert data["total"] == 2
    assert data["shares"][0]["name"] == "docker"


# ---------------------------------------------------------------------------
# list_packages
# ---------------------------------------------------------------------------

@respx.mock
@pytest.mark.asyncio
async def test_list_packages() -> None:
    payload = {
        "packages": [
            {"id": "ContainerManager", "version": "20.10.23-1455", "status": "running"},
            {"id": "HyperBackup", "version": "4.2.1-3390", "status": "running"},
        ],
        "total": 2,
    }
    respx.get(BASE_URL + "entry.cgi").mock(
        side_effect=[_LOGIN, httpx.Response(200, json=_dsm_ok(payload)), _LOGOUT]
    )
    async with SynologyClient(SETTINGS) as client:
        data = await client.list_packages()
    assert data["total"] == 2
    assert data["packages"][0]["id"] == "ContainerManager"


# ---------------------------------------------------------------------------
# list_scheduled_tasks
# ---------------------------------------------------------------------------

@respx.mock
@pytest.mark.asyncio
async def test_list_scheduled_tasks() -> None:
    payload = {
        "tasks": [
            {"id": 1, "name": "Backup-NAS", "enable": True, "status": "waiting"},
        ],
        "total": 1,
    }
    respx.get(BASE_URL + "entry.cgi").mock(
        side_effect=[_LOGIN, httpx.Response(200, json=_dsm_ok(payload)), _LOGOUT]
    )
    async with SynologyClient(SETTINGS) as client:
        data = await client.list_scheduled_tasks()
    assert data["tasks"][0]["name"] == "Backup-NAS"


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
        side_effect=[_LOGIN, httpx.Response(200, json=_dsm_ok(payload)), _LOGOUT]
    )
    async with SynologyClient(SETTINGS) as client:
        data = await client.list_docker_containers()
    assert data["total"] == 2


# ---------------------------------------------------------------------------
# list_docker_images
# ---------------------------------------------------------------------------

@respx.mock
@pytest.mark.asyncio
async def test_list_docker_images() -> None:
    payload = {
        "images": [
            {"id": "sha256:abc123", "name": "grafana/grafana", "tag": "latest", "size": 302000000},
        ],
        "total": 1,
    }
    respx.get(BASE_URL + "entry.cgi").mock(
        side_effect=[_LOGIN, httpx.Response(200, json=_dsm_ok(payload)), _LOGOUT]
    )
    async with SynologyClient(SETTINGS) as client:
        data = await client.list_docker_images()
    assert data["total"] == 1
    assert data["images"][0]["name"] == "grafana/grafana"


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
        side_effect=[_LOGIN, httpx.Response(200, json=_dsm_ok(payload)), _LOGOUT]
    )
    async with SynologyClient(SETTINGS) as client:
        data = await client.list_files("/docker")
    assert data["total"] == 2
    assert data["files"][0]["name"] == "compose.yml"


# ---------------------------------------------------------------------------
# get_security_status
# ---------------------------------------------------------------------------

@respx.mock
@pytest.mark.asyncio
async def test_get_security_status() -> None:
    payload = {
        "risk_item_cnt": {"critical": 0, "high": 1, "medium": 3, "low": 2, "info": 5},
        "last_scan_time": "2024-01-15 02:00:00",
    }
    respx.get(BASE_URL + "entry.cgi").mock(
        side_effect=[_LOGIN, httpx.Response(200, json=_dsm_ok(payload)), _LOGOUT]
    )
    async with SynologyClient(SETTINGS) as client:
        data = await client.get_security_status()
    assert data["risk_item_cnt"]["critical"] == 0


# ---------------------------------------------------------------------------
# get_backup_tasks
# ---------------------------------------------------------------------------

@respx.mock
@pytest.mark.asyncio
async def test_get_backup_tasks() -> None:
    payload = {
        "task_list": [
            {
                "id": 1,
                "name": "NAS-to-Cloud",
                "enable": True,
                "last_bkp_result": "success",
                "last_bkp_time": "2024-01-15 03:00:00",
            }
        ],
        "total": 1,
    }
    respx.get(BASE_URL + "entry.cgi").mock(
        side_effect=[_LOGIN, httpx.Response(200, json=_dsm_ok(payload)), _LOGOUT]
    )
    async with SynologyClient(SETTINGS) as client:
        data = await client.get_backup_tasks()
    assert data["task_list"][0]["last_bkp_result"] == "success"


# ---------------------------------------------------------------------------
# Context manager guard (no login attempted)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_client_without_context_manager_raises() -> None:
    client = SynologyClient(SETTINGS)
    with pytest.raises(RuntimeError, match="async context manager"):
        await client.query_api_info()
