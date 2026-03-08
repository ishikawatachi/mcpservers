"""
MCP HTTP Gateway
================
Exposes all local MCP stdio servers as HTTP/SSE endpoints so they can be
triggered from outside VS Code — e.g. by Perplexity, nanoclaw, openclaw,
or any MCP-compatible client that speaks HTTP.

Architecture
------------
Each MCP stdio server is launched as a subprocess (stdin/stdout protocol).
The gateway wraps each subprocess in an SSE endpoint so HTTP clients can
send JSON-RPC calls and receive streaming responses.

Usage
-----
    # Start all servers on their default ports
    python mcp_http_gateway.py

    # Start a single server
    python mcp_http_gateway.py --server portainer --port 9001

    # List configured servers
    python mcp_http_gateway.py --list

Ports (default)
---------------
  portainer  → http://127.0.0.1:9001/mcp
  proxmox    → http://127.0.0.1:9002/mcp
  synology   → http://127.0.0.1:9003/mcp
  authentik  → http://127.0.0.1:9004/mcp
  grafana    → http://127.0.0.1:9005/mcp

Perplexity connector snippet (settings.json)
--------------------------------------------
  "mcpServers": {
    "portainer": { "url": "http://127.0.0.1:9001/mcp" },
    "proxmox":   { "url": "http://127.0.0.1:9002/mcp" }
  }

Claude Desktop / nanoclaw / openclaw (claude_desktop_config.json)
-----------------------------------------------------------------
  "mcpServers": {
    "portainer": {
      "command": "<absolute-path-to-venv>/portainer-mcp"
    }
  }

  # OR, pointing at this gateway's HTTP port:
  "mcpServers": {
    "portainer": { "url": "http://127.0.0.1:9001/mcp" }
  }
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Server registry
# ---------------------------------------------------------------------------

BASE = Path(__file__).parent.parent  # git/mcp/

SERVERS: dict[str, dict] = {
    "portainer": {
        "command": str(BASE / "mcpportainer" / ".venv" / "bin" / "portainer-mcp"),
        "port": 9001,
    },
    "proxmox": {
        "command": str(BASE / "mcpproxmox" / ".venv" / "bin" / "proxmox-mcp"),
        "port": 9002,
    },
    "synology": {
        "command": str(BASE / "mcpsynology" / ".venv" / "bin" / "synology-mcp"),
        "port": 9003,
    },
    "authentik": {
        "command": str(BASE / "authentikmcp" / ".venv" / "bin" / "authentik-mcp"),
        "port": 9004,
    },
    "grafana": {
        "command": str(BASE / "grafanamcp" / ".venv" / "bin" / "grafana-mcp"),
        "port": 9005,
    },
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("mcp-gateway")


# ---------------------------------------------------------------------------
# Stdio ↔ HTTP bridge (per-server)
# ---------------------------------------------------------------------------

class StdioMCPBridge:
    """Manages a single stdio MCP subprocess and serialises JSON-RPC calls."""

    def __init__(self, name: str, command: str) -> None:
        self.name = name
        self._command = command
        self._proc: subprocess.Popen | None = None
        self._lock = asyncio.Lock()

    def _ensure_proc(self) -> subprocess.Popen:
        if self._proc is None or self._proc.poll() is not None:
            log.info("Starting %s subprocess: %s", self.name, self._command)
            self._proc = subprocess.Popen(
                [self._command],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=sys.stderr,
                text=True,
                bufsize=1,
            )
        return self._proc

    async def call(self, request: dict) -> dict:
        """Send a JSON-RPC request and return the response."""
        async with self._lock:
            proc = self._ensure_proc()
            assert proc.stdin and proc.stdout
            line = json.dumps(request) + "\n"
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, proc.stdin.write, line)
            await loop.run_in_executor(None, proc.stdin.flush)
            raw = await loop.run_in_executor(None, proc.stdout.readline)
            if not raw:
                raise RuntimeError(f"{self.name} MCP process closed unexpectedly")
            return json.loads(raw)

    def shutdown(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()


# ---------------------------------------------------------------------------
# HTTP server (Starlette/ASGI)
# ---------------------------------------------------------------------------

def _make_app(bridge: StdioMCPBridge):
    try:
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import JSONResponse, StreamingResponse
        from starlette.routing import Route
    except ImportError:
        sys.exit(
            "Install starlette+uvicorn: pip install starlette uvicorn"
        )

    async def handle_mcp(request: Request):
        body = await request.json()
        # Normalise to JSON-RPC 2.0 if the caller sends MCP envelope format
        if "jsonrpc" not in body:
            # Perplexity / plain-object format  →  wrap in JSON-RPC
            method = body.get("name") or body.get("command", "")
            params = body.get("tool_args") or body.get("args") or {}
            body = {
                "jsonrpc": "2.0",
                "id": body.get("id", 1),
                "method": "tools/call",
                "params": {"name": method, "arguments": params},
            }
        try:
            result = await bridge.call(body)
            return JSONResponse(result)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    async def health(_: Request):
        return JSONResponse({"server": bridge.name, "status": "ok"})

    return Starlette(routes=[
        Route("/mcp", handle_mcp, methods=["POST"]),
        Route("/health", health, methods=["GET"]),
    ])


def run_server(name: str, port: int) -> None:
    """Run a single MCP server HTTP gateway."""
    try:
        import uvicorn
    except ImportError:
        sys.exit("Install uvicorn: pip install uvicorn")

    cfg = SERVERS[name]
    bridge = StdioMCPBridge(name, cfg["command"])
    app = _make_app(bridge)
    log.info("Gateway for '%s' listening on http://127.0.0.1:%d/mcp", name, port)
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    finally:
        bridge.shutdown()


# ---------------------------------------------------------------------------
# Multi-server launcher
# ---------------------------------------------------------------------------

def run_all() -> None:
    """Launch all gateways in parallel subprocesses."""
    procs = []
    for name, cfg in SERVERS.items():
        p = subprocess.Popen(
            [sys.executable, __file__, "--server", name, "--port", str(cfg["port"])],
            stderr=sys.stderr,
        )
        procs.append((name, p))
        log.info("Launched gateway for '%s' on port %d (pid=%d)", name, cfg["port"], p.pid)

    log.info("All gateways running. Press Ctrl+C to stop.")
    try:
        for _, p in procs:
            p.wait()
    except KeyboardInterrupt:
        log.info("Shutting down all gateways…")
        for _, p in procs:
            p.terminate()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="MCP HTTP Gateway")
    parser.add_argument("--server", choices=list(SERVERS), help="Single server to run")
    parser.add_argument("--port", type=int, help="Override port for --server")
    parser.add_argument("--list", action="store_true", help="List configured servers")
    args = parser.parse_args()

    if args.list:
        print("Configured MCP servers:")
        for name, cfg in SERVERS.items():
            print(f"  {name:12s}  port={cfg['port']}  cmd={cfg['command']}")
        return

    if args.server:
        port = args.port or SERVERS[args.server]["port"]
        run_server(args.server, port)
    else:
        run_all()


if __name__ == "__main__":
    main()
