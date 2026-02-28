"""Tests for ProxmoxClient."""
from __future__ import annotations

import pytest
import respx
import httpx
from unittest.mock import MagicMock

from proxmox_mcp.client import ProxmoxClient, ProxmoxAPIError
from proxmox_mcp.config import Settings


def make_settings(**kwargs) -> Settings:
    base = dict(
        proxmox_url="https://pm.example.com",
        api_token="root@pam!mcp=test-uuid-1234",
        ssl_verify=False,
        timeout=5.0,
    )
    base.update(kwargs)
    return Settings(**base)


BASE = "https://pm.example.com/api2/json/"


@respx.mock
@pytest.mark.asyncio
async def test_health_check_ok():
    respx.get(f"{BASE}version").mock(
        return_value=httpx.Response(200, json={"data": {"version": "8.1", "release": "1"}})
    )
    async with ProxmoxClient(make_settings()) as client:
        result = await client.get_version()
    assert result["version"] == "8.1"


@respx.mock
@pytest.mark.asyncio
async def test_list_nodes():
    respx.get(f"{BASE}nodes").mock(
        return_value=httpx.Response(200, json={"data": [
            {"node": "pve", "status": "online", "cpu": 0.05, "maxcpu": 8,
             "mem": 4_294_967_296, "maxmem": 16_000_000_000, "uptime": 100000}
        ]})
    )
    async with ProxmoxClient(make_settings()) as client:
        nodes = await client.list_nodes()
    assert len(nodes) == 1
    assert nodes[0]["node"] == "pve"


@respx.mock
@pytest.mark.asyncio
async def test_list_vms():
    respx.get(f"{BASE}nodes/pve/qemu").mock(
        return_value=httpx.Response(200, json={"data": [
            {"vmid": 100, "name": "ubuntu", "status": "running",
             "cpu": 0.02, "cpus": 2, "mem": 1_073_741_824, "maxmem": 2_147_483_648}
        ]})
    )
    async with ProxmoxClient(make_settings()) as client:
        vms = await client.list_vms("pve")
    assert vms[0]["vmid"] == 100
    assert vms[0]["name"] == "ubuntu"


@respx.mock
@pytest.mark.asyncio
async def test_start_vm():
    respx.post(f"{BASE}nodes/pve/qemu/100/status/start").mock(
        return_value=httpx.Response(200, json={"data": "UPID:pve:001:start"})
    )
    async with ProxmoxClient(make_settings()) as client:
        task = await client.start_vm("pve", 100)
    assert "UPID" in task


@respx.mock
@pytest.mark.asyncio
async def test_stop_vm():
    respx.post(f"{BASE}nodes/pve/qemu/100/status/stop").mock(
        return_value=httpx.Response(200, json={"data": "UPID:pve:001:stop"})
    )
    async with ProxmoxClient(make_settings()) as client:
        task = await client.stop_vm("pve", 100)
    assert "UPID" in task


@respx.mock
@pytest.mark.asyncio
async def test_list_lxc():
    respx.get(f"{BASE}nodes/pve/lxc").mock(
        return_value=httpx.Response(200, json={"data": [
            {"vmid": 200, "name": "nginx-ct", "status": "running"}
        ]})
    )
    async with ProxmoxClient(make_settings()) as client:
        ctrs = await client.list_lxc("pve")
    assert ctrs[0]["vmid"] == 200


@respx.mock
@pytest.mark.asyncio
async def test_unauthorized_raises():
    respx.get(f"{BASE}version").mock(return_value=httpx.Response(401, text="unauthorized"))
    with pytest.raises(ProxmoxAPIError) as exc_info:
        async with ProxmoxClient(make_settings()) as client:
            await client.get_version()
    assert exc_info.value.status_code == 401


@respx.mock
@pytest.mark.asyncio
async def test_list_storages():
    respx.get(f"{BASE}nodes/pve/storage").mock(
        return_value=httpx.Response(200, json={"data": [
            {"storage": "local", "type": "dir", "status": "available",
             "active": 1, "enabled": 1, "used": 10_737_418_240,
             "avail": 50_000_000_000, "total": 60_737_418_240,
             "content": "iso,vztmpl,backup"}
        ]})
    )
    async with ProxmoxClient(make_settings()) as client:
        storages = await client.list_storages("pve")
    assert storages[0]["storage"] == "local"
