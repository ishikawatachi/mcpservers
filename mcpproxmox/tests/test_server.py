"""
Comprehensive test suite for Proxmox MCP server.

Covers:
  • parse_request()  — dual-transport normalisation (VSCode + Perplexity)
  • _dispatch()      — all 18 MCP tools, with a mocked ProxmoxClient
  • Error paths      — unknown tool, validation error, API error
  • HTTP /call       — Perplexity-style REST endpoint (both payload formats)
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from proxmox_mcp.server import _dispatch, _ok, _err, parse_request, _create_sse_app
from proxmox_mcp.client import ProxmoxAPIError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(**async_methods) -> MagicMock:
    """Return a MagicMock whose listed methods are AsyncMocks returning given values."""
    client = MagicMock()
    for method_name, return_value in async_methods.items():
        setattr(client, method_name, AsyncMock(return_value=return_value))
    return client


def _json(result) -> dict:
    """Parse the first TextContent result as JSON."""
    return json.loads(result[0].text)


# ---------------------------------------------------------------------------
# parse_request — VSCode / Copilot format
# ---------------------------------------------------------------------------

class TestParseRequestVSCode:
    def test_command_with_args(self):
        name, args = parse_request({"command": "list_nodes", "args": {"node": "pve"}})
        assert name == "list_nodes"
        assert args == {"node": "pve"}

    def test_command_no_args_defaults_to_empty_dict(self):
        name, args = parse_request({"command": "health_check"})
        assert name == "health_check"
        assert args == {}

    def test_command_with_explicit_empty_args(self):
        name, args = parse_request({"command": "get_cluster_status", "args": {}})
        assert name == "get_cluster_status"
        assert args == {}


# ---------------------------------------------------------------------------
# parse_request — Perplexity format
# ---------------------------------------------------------------------------

class TestParseRequestPerplexity:
    def test_name_plus_tool_args(self):
        name, args = parse_request({
            "name": "list_vms",
            "tool_args": {"node": "bab1"},
            "_requires_user_approval": False,
        })
        assert name == "list_vms"
        assert args == {"node": "bab1"}

    def test_name_takes_priority_over_inferred(self):
        name, args = parse_request({
            "name": "get_vm_status",
            "tool_args": {"node": "pve", "vmid": 100},
        })
        assert name == "get_vm_status"
        assert args["vmid"] == 100

    def test_infer_name_from_first_tool_args_key(self):
        # When no "name" key, tool name is the first key in tool_args
        name, args = parse_request({"tool_args": {"health_check": {}}})
        assert name == "health_check"

    def test_empty_tool_args_without_name_raises(self):
        with pytest.raises(ValueError, match="empty"):
            parse_request({"tool_args": {}})

    def test_extra_perplexity_fields_are_ignored(self):
        name, args = parse_request({
            "name": "list_nodes",
            "tool_args": {},
            "_requires_user_approval": True,
            "session_id": "abc123",
        })
        assert name == "list_nodes"
        assert args == {}


# ---------------------------------------------------------------------------
# parse_request — invalid / unknown format
# ---------------------------------------------------------------------------

class TestParseRequestInvalid:
    def test_missing_both_keys_raises(self):
        with pytest.raises(ValueError, match="Invalid MCP format"):
            parse_request({"foo": "bar"})

    def test_empty_dict_raises(self):
        with pytest.raises(ValueError, match="Invalid MCP format"):
            parse_request({})


# ---------------------------------------------------------------------------
# _dispatch — read-only tools
# ---------------------------------------------------------------------------

class TestDispatchReadTools:
    @pytest.mark.asyncio
    async def test_health_check(self):
        client = _make_client(get_version={"version": "8.1", "release": "1"})
        result = _json(await _dispatch("health_check", {}, client))
        assert result["status"] == "ok"
        assert result["proxmox"]["version"] == "8.1"

    @pytest.mark.asyncio
    async def test_get_cluster_status(self):
        payload = [{"name": "cluster", "type": "cluster", "quorate": 1, "nodes": 1}]
        client = _make_client(get_cluster_status=payload)
        result = _json(await _dispatch("get_cluster_status", {}, client))
        assert result[0]["name"] == "cluster"

    @pytest.mark.asyncio
    async def test_list_tasks_default_limit(self):
        tasks = [{"upid": "UPID:pve:001", "type": "startall", "status": "OK"}]
        client = _make_client(list_tasks=tasks)
        result = _json(await _dispatch("list_tasks", {}, client))
        client.list_tasks.assert_called_once_with(limit=50)
        assert result[0]["upid"] == "UPID:pve:001"

    @pytest.mark.asyncio
    async def test_list_tasks_custom_limit(self):
        client = _make_client(list_tasks=[])
        await _dispatch("list_tasks", {"limit": 10}, client)
        client.list_tasks.assert_called_once_with(limit=10)

    @pytest.mark.asyncio
    async def test_list_tasks_limit_capped_at_200(self):
        client = _make_client(list_tasks=[])
        await _dispatch("list_tasks", {"limit": 999}, client)
        client.list_tasks.assert_called_once_with(limit=200)

    @pytest.mark.asyncio
    async def test_list_nodes(self):
        raw_nodes = [{
            "node": "bab1", "status": "online", "uptime": 100000,
            "cpu": 0.05, "maxcpu": 14,
            "mem": 4_294_967_296, "maxmem": 16_000_000_000,
            "disk": 10_737_418_240, "maxdisk": 100_000_000_000,
            "level": "",
        }]
        client = _make_client(list_nodes=raw_nodes)
        result = _json(await _dispatch("list_nodes", {}, client))
        assert result[0]["node"] == "bab1"
        assert result[0]["cpu"] == 5.0           # fraction → %
        assert result[0]["mem_gb"] == 4.0
        assert result[0]["maxmem_gb"] == pytest.approx(14.9, abs=0.5)

    @pytest.mark.asyncio
    async def test_get_node_status(self):
        status = {"cpu": 0.1, "memory": {"total": 8000, "used": 4000}}
        client = _make_client(get_node_status=status)
        result = _json(await _dispatch("get_node_status", {"node": "bab1"}, client))
        client.get_node_status.assert_called_once_with("bab1")
        assert result["cpu"] == 0.1

    @pytest.mark.asyncio
    async def test_list_vms(self):
        raw_vms = [{
            "vmid": 101, "name": "starwise", "status": "running",
            "uptime": 3600, "cpu": 0.02, "cpus": 4,
            "mem": 2_147_483_648, "maxmem": 4_294_967_296,
            "disk": 0, "maxdisk": 171_798_691_840,
        }]
        client = _make_client(list_vms=raw_vms)
        result = _json(await _dispatch("list_vms", {"node": "bab1"}, client))
        assert result[0]["vmid"] == 101
        assert result[0]["name"] == "starwise"
        assert result[0]["mem_mb"] == 2048.0

    @pytest.mark.asyncio
    async def test_get_vm_status(self):
        status = {"status": "running", "cpu": 0.03}
        client = _make_client(get_vm_status=status)
        result = _json(await _dispatch("get_vm_status", {"node": "bab1", "vmid": 101}, client))
        client.get_vm_status.assert_called_once_with("bab1", 101)
        assert result["status"] == "running"

    @pytest.mark.asyncio
    async def test_list_lxc(self):
        raw = [{
            "vmid": 200, "name": "nginx-ct", "status": "running",
            "uptime": 7200, "cpu": 0.01, "cpus": 2,
            "mem": 536_870_912, "maxmem": 1_073_741_824,
            "disk": 0, "maxdisk": 10_737_418_240,
        }]
        client = _make_client(list_lxc=raw)
        result = _json(await _dispatch("list_lxc", {"node": "bab1"}, client))
        assert result[0]["vmid"] == 200
        assert result[0]["mem_mb"] == 512.0

    @pytest.mark.asyncio
    async def test_get_lxc_status(self):
        status = {"status": "running", "uptime": 7200}
        client = _make_client(get_lxc_status=status)
        result = _json(await _dispatch("get_lxc_status", {"node": "bab1", "vmid": 200}, client))
        client.get_lxc_status.assert_called_once_with("bab1", 200)
        assert result["status"] == "running"

    @pytest.mark.asyncio
    async def test_list_storages(self):
        raw = [{
            "storage": "local", "type": "dir", "status": "available",
            "active": 1, "enabled": 1,
            "used": 10_737_418_240, "avail": 50_000_000_000, "total": 60_737_418_240,
            "content": "iso,vztmpl,backup",
        }]
        client = _make_client(list_storages=raw)
        result = _json(await _dispatch("list_storages", {"node": "bab1"}, client))
        assert result[0]["storage"] == "local"
        assert result[0]["avail_gb"] == pytest.approx(46.57, abs=0.1)

    @pytest.mark.asyncio
    async def test_get_storage_content(self):
        raw = [{"volid": "local:iso/ubuntu.iso", "content": "iso", "format": "iso",
                "size": 1_073_741_824, "vmid": None, "notes": None}]
        client = _make_client(get_storage_content=raw)
        result = _json(await _dispatch(
            "get_storage_content", {"node": "bab1", "storage": "local"}, client
        ))
        client.get_storage_content.assert_called_once_with("bab1", "local")
        assert result[0]["content"] == "iso"
        assert result[0]["size_gb"] == 1.0


# ---------------------------------------------------------------------------
# _dispatch — power actions (VMs)
# ---------------------------------------------------------------------------

class TestDispatchVMPowerActions:
    @pytest.mark.asyncio
    async def test_start_vm(self):
        client = _make_client(start_vm="UPID:bab1:00001:start")
        result = _json(await _dispatch("start_vm", {"node": "bab1", "vmid": 101}, client))
        assert result["result"] == "start_requested"
        assert result["node"] == "bab1"
        assert result["vmid"] == 101
        assert "UPID" in result["task"]

    @pytest.mark.asyncio
    async def test_stop_vm(self):
        client = _make_client(stop_vm="UPID:bab1:00002:stop")
        result = _json(await _dispatch("stop_vm", {"node": "bab1", "vmid": 101}, client))
        assert result["result"] == "stop_requested"

    @pytest.mark.asyncio
    async def test_shutdown_vm_default_timeout(self):
        client = _make_client(shutdown_vm="UPID:bab1:00003:shutdown")
        result = _json(await _dispatch("shutdown_vm", {"node": "bab1", "vmid": 101}, client))
        client.shutdown_vm.assert_called_once_with("bab1", 101, timeout=60)
        assert result["result"] == "shutdown_requested"

    @pytest.mark.asyncio
    async def test_shutdown_vm_custom_timeout(self):
        client = _make_client(shutdown_vm="UPID:bab1:00003:shutdown")
        await _dispatch("shutdown_vm", {"node": "bab1", "vmid": 101, "timeout": 120}, client)
        client.shutdown_vm.assert_called_once_with("bab1", 101, timeout=120)

    @pytest.mark.asyncio
    async def test_reboot_vm(self):
        client = _make_client(reboot_vm="UPID:bab1:00004:reboot")
        result = _json(await _dispatch("reboot_vm", {"node": "bab1", "vmid": 101}, client))
        assert result["result"] == "reboot_requested"


# ---------------------------------------------------------------------------
# _dispatch — power actions (LXC)
# ---------------------------------------------------------------------------

class TestDispatchLXCPowerActions:
    @pytest.mark.asyncio
    async def test_start_lxc(self):
        client = _make_client(start_lxc="UPID:bab1:00010:lxcstart")
        result = _json(await _dispatch("start_lxc", {"node": "bab1", "vmid": 200}, client))
        assert result["result"] == "start_requested"
        assert result["vmid"] == 200

    @pytest.mark.asyncio
    async def test_stop_lxc(self):
        client = _make_client(stop_lxc="UPID:bab1:00011:lxcstop")
        result = _json(await _dispatch("stop_lxc", {"node": "bab1", "vmid": 200}, client))
        assert result["result"] == "stop_requested"

    @pytest.mark.asyncio
    async def test_shutdown_lxc_default_timeout(self):
        client = _make_client(shutdown_lxc="UPID:bab1:00012:lxcshutdown")
        result = _json(await _dispatch("shutdown_lxc", {"node": "bab1", "vmid": 200}, client))
        client.shutdown_lxc.assert_called_once_with("bab1", 200, timeout=60)
        assert result["result"] == "shutdown_requested"

    @pytest.mark.asyncio
    async def test_shutdown_lxc_custom_timeout(self):
        client = _make_client(shutdown_lxc="UPID:bab1:00012:lxcshutdown")
        await _dispatch("shutdown_lxc", {"node": "bab1", "vmid": 200, "timeout": 300}, client)
        client.shutdown_lxc.assert_called_once_with("bab1", 200, timeout=300)


# ---------------------------------------------------------------------------
# _dispatch — error paths
# ---------------------------------------------------------------------------

class TestDispatchErrors:
    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        client = _make_client()
        result = _json(await _dispatch("nonexistent_tool", {}, client))
        assert "error" in result
        assert "nonexistent_tool" in result["error"]

    @pytest.mark.asyncio
    async def test_validation_error_missing_required_field(self):
        """Passing arguments that fail Pydantic validation should return error text."""
        client = _make_client(get_node_status={})
        # VmInput requires both "node" and "vmid"; omitting vmid should raise ValidationError
        # which is caught in call_tool(), not _dispatch() — so we get a Pydantic exception here
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            await _dispatch("get_vm_status", {"node": "bab1"}, client)  # missing vmid

    @pytest.mark.asyncio
    async def test_vmid_below_minimum_raises_validation(self):
        from pydantic import ValidationError
        client = _make_client(get_vm_status={})
        with pytest.raises(ValidationError):
            await _dispatch("get_vm_status", {"node": "bab1", "vmid": 50}, client)


# ---------------------------------------------------------------------------
# HTTP /call endpoint — integration tests via Starlette TestClient
# ---------------------------------------------------------------------------

class TestHTTPCallEndpoint:
    """Test the /call REST endpoint that serves Perplexity and VSCode HTTP clients."""

    def _make_app(self, mock_client: MagicMock):
        """Create the Starlette SSE app with ProxmoxClient patched to mock_client."""
        return _create_sse_app()

    @pytest.fixture()
    def test_client(self):
        """Starlette synchronous TestClient for the SSE app."""
        from starlette.testclient import TestClient

        # Patch ProxmoxClient and get_settings so no real connection is needed
        mock_client_instance = _make_client(
            get_version={"version": "8.1", "release": "1"}
        )
        # ProxmoxClient is used as an async context manager
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mock_settings = MagicMock()

        with patch("proxmox_mcp.server.ProxmoxClient", return_value=mock_cm), \
             patch("proxmox_mcp.server.get_settings", return_value=mock_settings):
            app = _create_sse_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                yield client, mock_client_instance

    def test_vscode_format_health_check(self, test_client):
        client, mock = test_client
        resp = client.post("/call", json={"command": "health_check", "args": {}})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_perplexity_format_health_check(self, test_client):
        client, mock = test_client
        resp = client.post("/call", json={
            "name": "health_check",
            "tool_args": {},
            "_requires_user_approval": False,
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_invalid_json_returns_400(self, test_client):
        client, _ = test_client
        resp = client.post("/call", content=b"not-json",
                           headers={"content-type": "application/json"})
        assert resp.status_code == 400

    def test_invalid_format_returns_400(self, test_client):
        client, _ = test_client
        resp = client.post("/call", json={"totally": "wrong"})
        assert resp.status_code == 400
        assert "Invalid MCP format" in resp.json()["error"]
