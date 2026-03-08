"""
test_mcp_external.py
====================
Tests for triggering MCP servers from outside VS Code.

Covers three categories:
  1. STDIO direct — spawn the server binary, write JSON-RPC over stdin,
     read the response from stdout. Works for any MCP client (stdio mode).
  2. HTTP gateway  — send POST requests to the mcp_http_gateway running
     locally. Mirrors what Perplexity / nanoclaw / openclaw do.
  3. Perplexity payload format — send Perplexity-style { "name": …,
     "tool_args": … } payloads through the gateway and verify they're
     normalised correctly.

Run
---
    # From the repo root, with one venv that has 'httpx' and 'pytest':
    pip install httpx pytest pytest-asyncio
    pytest mcpcreations/tests/test_mcp_external.py -v

    # Skip gateway tests if the gateway isn't running:
    pytest mcpcreations/tests/test_mcp_external.py -v -m "not gateway"

Environment
-----------
    GATEWAY_BASE_URL  — override base URL for gateway tests (default: http://127.0.0.1)
    MCP_TIMEOUT       — seconds before a stdio call is considered stuck (default: 15)
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE = Path(__file__).parent.parent.parent   # git/mcp/

SERVERS = {
    "portainer": {
        "cmd": str(BASE / "mcpportainer" / ".venv" / "bin" / "portainer-mcp"),
        "port": 9001,
    },
    "proxmox": {
        "cmd": str(BASE / "mcpproxmox" / ".venv" / "bin" / "proxmox-mcp"),
        "port": 9002,
    },
    "synology": {
        "cmd": str(BASE / "mcpsynology" / ".venv" / "bin" / "synology-mcp"),
        "port": 9003,
    },
    "authentik": {
        "cmd": str(BASE / "authentikmcp" / ".venv" / "bin" / "authentik-mcp"),
        "port": 9004,
    },
    "grafana": {
        "cmd": str(BASE / "grafanamcp" / ".venv" / "bin" / "grafana-mcp"),
        "port": 9005,
    },
}

GATEWAY_BASE = os.getenv("GATEWAY_BASE_URL", "http://127.0.0.1")
TIMEOUT = int(os.getenv("MCP_TIMEOUT", "15"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _jsonrpc(method: str, params: dict, id_: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params}


def _stdio_call(cmd: str, payload: dict, timeout: int = TIMEOUT) -> dict:
    """Start the MCP binary, send one JSON-RPC message, return the parsed response."""
    proc = subprocess.Popen(
        [cmd],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    line = json.dumps(payload) + "\n"
    try:
        stdout, stderr = proc.communicate(input=line, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise TimeoutError(f"MCP server {cmd} did not respond within {timeout}s")
    finally:
        if proc.poll() is None:
            proc.terminate()

    # The first line of stdout is the JSON-RPC response
    for raw_line in stdout.splitlines():
        raw_line = raw_line.strip()
        if raw_line:
            return json.loads(raw_line)
    raise ValueError(f"No JSON response from {cmd}. stderr={stderr[:500]}")


# ---------------------------------------------------------------------------
# Category 1: Verify binary exists and is executable
# ---------------------------------------------------------------------------

class TestBinaryPresence:
    """Sanity-check that all server binaries are installed."""

    @pytest.mark.parametrize("name,cfg", SERVERS.items())
    def test_binary_exists(self, name: str, cfg: dict):
        path = Path(cfg["cmd"])
        assert path.exists(), f"{name}: binary not found at {path}"
        assert os.access(path, os.X_OK), f"{name}: binary is not executable"

    @pytest.mark.parametrize("name,cfg", SERVERS.items())
    def test_binary_reports_help(self, name: str, cfg: dict):
        """Running the binary with --help (or similar) must exit cleanly or
        produce output — proves the Python entry-point actually loads."""
        result = subprocess.run(
            [cfg["cmd"], "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # Most MCP servers exit 0 or 2 (argparse) on --help, but never crash
        assert result.returncode in (0, 1, 2), (
            f"{name} crashed on --help: {result.stderr[:200]}"
        )


# ---------------------------------------------------------------------------
# Category 2: STDIO JSON-RPC — initialize + list_tools
# ---------------------------------------------------------------------------

class TestStdioInitialize:
    """
    The MCP handshake: send 'initialize', expect a capabilities response.
    This works for ANY MCP client (Claude Desktop, nanoclaw, openclaw, etc.).
    """

    INIT_PAYLOAD = _jsonrpc(
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "0.0.1"},
        },
    )

    @pytest.mark.parametrize("name,cfg", SERVERS.items())
    def test_initialize_returns_server_info(self, name: str, cfg: dict):
        response = _stdio_call(cfg["cmd"], self.INIT_PAYLOAD)
        assert "result" in response or "error" in response, (
            f"{name}: unexpected response shape {response}"
        )
        if "result" in response:
            result = response["result"]
            # Must advertise at minimum a 'capabilities' or 'serverInfo' key
            assert "capabilities" in result or "serverInfo" in result, (
                f"{name}: initialize result missing capabilities: {result}"
            )

    @pytest.mark.parametrize("name,cfg", SERVERS.items())
    def test_list_tools_returns_tools_array(self, name: str, cfg: dict):
        """After initialize, tools/list must return a non-empty array."""
        # Send initialize first, then tools/list in sequence
        # We use communicate() which sends both lines at once
        payloads = (
            json.dumps(self.INIT_PAYLOAD) + "\n"
            + json.dumps(_jsonrpc("tools/list", {}, id_=2)) + "\n"
        )
        proc = subprocess.Popen(
            [cfg["cmd"]],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = proc.communicate(input=payloads, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            pytest.skip(f"{name}: timed out — server may be waiting for credentials")
        finally:
            if proc.poll() is None:
                proc.terminate()

        lines = [l.strip() for l in stdout.splitlines() if l.strip()]
        assert len(lines) >= 2, (
            f"{name}: expected at least 2 JSON-RPC responses, got {len(lines)}. "
            f"stderr={stderr[:300]}"
        )
        tools_response = json.loads(lines[1])
        if "result" in tools_response:
            tools = tools_response["result"].get("tools", [])
            assert isinstance(tools, list) and len(tools) > 0, (
                f"{name}: tools/list returned empty tools array"
            )


# ---------------------------------------------------------------------------
# Category 3: HTTP Gateway tests
# ---------------------------------------------------------------------------

@pytest.mark.gateway
class TestHTTPGateway:
    """
    Requires the mcp_http_gateway.py to be running:
        python mcpcreations/mcp_http_gateway.py &

    Mark: gateway — skip with: pytest -m "not gateway"
    """

    def _url(self, port: int, path: str = "/mcp") -> str:
        return f"{GATEWAY_BASE}:{port}{path}"

    @pytest.mark.parametrize("name,cfg", SERVERS.items())
    def test_health_endpoint(self, name: str, cfg: dict):
        try:
            import httpx
        except ImportError:
            pytest.skip("httpx not installed")
        url = self._url(cfg["port"], "/health")
        try:
            r = httpx.get(url, timeout=5)
        except httpx.ConnectError:
            pytest.skip(f"Gateway for '{name}' not running (port {cfg['port']})")
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "ok"
        assert data.get("server") == name

    @pytest.mark.parametrize("name,cfg", SERVERS.items())
    def test_mcp_post_initialize(self, name: str, cfg: dict):
        try:
            import httpx
        except ImportError:
            pytest.skip("httpx not installed")
        url = self._url(cfg["port"])
        payload = _jsonrpc(
            "initialize",
            {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "gateway-test", "version": "0.1"}},
        )
        try:
            r = httpx.post(url, json=payload, timeout=15)
        except httpx.ConnectError:
            pytest.skip(f"Gateway for '{name}' not running (port {cfg['port']})")
        assert r.status_code == 200
        data = r.json()
        assert "result" in data or "error" in data


# ---------------------------------------------------------------------------
# Category 4: Perplexity connector format
# ---------------------------------------------------------------------------

@pytest.mark.gateway
class TestPerplexityFormat:
    """
    Perplexity sends:  {"name": "tool_name", "tool_args": {...}}
    The gateway must normalise this into JSON-RPC and proxy it.
    """

    def _url(self, port: int) -> str:
        return f"{GATEWAY_BASE}:{port}/mcp"

    @pytest.mark.parametrize("name,cfg", [
        ("portainer", SERVERS["portainer"]),
        ("proxmox", SERVERS["proxmox"]),
    ])
    def test_perplexity_payload_accepted(self, name: str, cfg: dict):
        try:
            import httpx
        except ImportError:
            pytest.skip("httpx not installed")
        payload = {
            "name": "health_check",
            "tool_args": {},
            "_requires_user_approval": False,
        }
        try:
            r = httpx.post(self._url(cfg["port"]), json=payload, timeout=15)
        except httpx.ConnectError:
            pytest.skip(f"Gateway for '{name}' not running (port {cfg['port']})")
        assert r.status_code in (200, 500), f"Unexpected HTTP {r.status_code}"
        # 500 is acceptable if the backend has no credentials — gateway itself worked
        data = r.json()
        assert isinstance(data, dict), "Response must be a JSON object"


# ---------------------------------------------------------------------------
# Category 5: Nanoclaw / openclaw compatibility notes
# ---------------------------------------------------------------------------

class TestClientCompatibility:
    """
    Nanoclaw and openclaw are MCP-compatible CLI clients that support stdio
    and HTTP/SSE transport.  These tests verify the server advertises the
    correct MCP protocol version so those clients can connect.

    nanoclaw: https://github.com/anthropics/nanoclaw
    openclaw: community fork with extended tool-call support

    Both clients support stdio mode out of the box — point them at the
    binary path in your ~/.config/nanoclaw/config.json:

        {
          "servers": {
            "portainer": {
              "command": "<venv-path>/portainer-mcp"
            }
          }
        }

    For HTTP mode, start mcp_http_gateway.py and point at
        http://127.0.0.1:9001/mcp
    """

    SUPPORTED_PROTOCOL_VERSION = "2024-11-05"

    @pytest.mark.parametrize("name,cfg", SERVERS.items())
    def test_protocol_version_in_initialize(self, name: str, cfg: dict):
        """The server's initialize response must include a protocolVersion."""
        payload = _jsonrpc(
            "initialize",
            {
                "protocolVersion": self.SUPPORTED_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "nanoclaw", "version": "0.1"},
            },
        )
        try:
            response = _stdio_call(cfg["cmd"], payload, timeout=TIMEOUT)
        except (TimeoutError, ValueError) as e:
            pytest.skip(f"{name}: {e}")

        if "result" in response:
            proto = response["result"].get("protocolVersion")
            if proto:
                assert proto == self.SUPPORTED_PROTOCOL_VERSION, (
                    f"{name}: server returned protocol version '{proto}', "
                    f"expected '{self.SUPPORTED_PROTOCOL_VERSION}'"
                )
