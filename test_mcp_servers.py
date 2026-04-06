#!/usr/bin/env python3
"""Test all MCP server binaries for proper startup and protocol compliance."""

import subprocess
import json
import select
import sys
import os

BASE = os.path.dirname(os.path.abspath(__file__))

SERVERS = {
    "portainer": f"{BASE}/mcpportainer/.venv/bin/portainer-mcp",
    "proxmox": f"{BASE}/mcpproxmox/.venv/bin/proxmox-mcp",
    "synology": f"{BASE}/mcpsynology/.venv/bin/synology-mcp",
    "authentik": f"{BASE}/authentikmcp/.venv/bin/authentik-mcp",
    "grafana": f"{BASE}/grafanamcp/.venv/bin/grafana-mcp",
}

INIT_MSG = json.dumps({
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test-harness", "version": "1.0"}
    }
}) + "\n"

TOOLS_MSG = json.dumps({
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
    "params": {}
}) + "\n"

INITIALIZED_MSG = json.dumps({
    "jsonrpc": "2.0",
    "method": "notifications/initialized",
    "params": {}
}) + "\n"


def test_server(name, binary):
    print(f"\n{'='*50}")
    print(f"  Testing: {name}")
    print(f"  Binary:  {binary}")
    print(f"{'='*50}")

    # Check binary exists
    if not os.path.isfile(binary):
        print(f"  FAIL: Binary not found")
        return False

    if not os.access(binary, os.X_OK):
        print(f"  FAIL: Binary not executable")
        return False

    print(f"  Binary exists and is executable: OK")

    try:
        proc = subprocess.Popen(
            [binary],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except Exception as e:
        print(f"  FAIL: Could not start process: {e}")
        return False

    print(f"  Process started (PID {proc.pid}): OK")

    # Send initialize
    try:
        proc.stdin.write(INIT_MSG.encode())
        proc.stdin.flush()
    except Exception as e:
        print(f"  FAIL: Could not send initialize: {e}")
        proc.terminate()
        return False

    # Wait for response
    ready, _, _ = select.select([proc.stdout], [], [], 8)
    if not ready:
        print(f"  FAIL: No response to initialize within 8 seconds")
        # Check stderr
        stderr_ready, _, _ = select.select([proc.stderr], [], [], 1)
        if stderr_ready:
            err = proc.stderr.read(2000).decode(errors="replace")
            print(f"  STDERR: {err[:500]}")
        proc.terminate()
        return False

    line = proc.stdout.readline().decode().strip()
    if not line:
        print(f"  FAIL: Empty response")
        proc.terminate()
        return False

    try:
        resp = json.loads(line)
    except json.JSONDecodeError as e:
        print(f"  FAIL: Invalid JSON response: {e}")
        print(f"  Raw: {line[:300]}")
        proc.terminate()
        return False

    if "result" not in resp:
        print(f"  FAIL: No 'result' in response: {json.dumps(resp)[:300]}")
        proc.terminate()
        return False

    result = resp["result"]
    server_info = result.get("serverInfo", {})
    capabilities = result.get("capabilities", {})

    print(f"  Initialize response: OK")
    print(f"  Server: {server_info.get('name', '?')} v{server_info.get('version', '?')}")
    print(f"  Protocol: {result.get('protocolVersion', '?')}")
    print(f"  Capabilities: {list(capabilities.keys())}")

    # Send initialized notification + tools/list
    try:
        proc.stdin.write(INITIALIZED_MSG.encode())
        proc.stdin.flush()
        proc.stdin.write(TOOLS_MSG.encode())
        proc.stdin.flush()
    except Exception as e:
        print(f"  WARN: Could not send tools/list: {e}")
        proc.terminate()
        return True  # init worked at least

    ready2, _, _ = select.select([proc.stdout], [], [], 8)
    if ready2:
        line2 = proc.stdout.readline().decode().strip()
        if line2:
            try:
                resp2 = json.loads(line2)
                if "result" in resp2:
                    tools = resp2["result"].get("tools", [])
                    print(f"  Tools available: {len(tools)}")
                    for t in tools:
                        print(f"    - {t.get('name', '?')}: {t.get('description', '?')[:60]}")
                else:
                    print(f"  tools/list response (no result): {line2[:200]}")
            except json.JSONDecodeError:
                print(f"  WARN: Invalid JSON for tools/list: {line2[:200]}")
    else:
        print(f"  WARN: No tools/list response within 8 seconds")

    # Check stderr for warnings
    stderr_ready, _, _ = select.select([proc.stderr], [], [], 0.5)
    if stderr_ready:
        err = proc.stderr.read(2000).decode(errors="replace")
        if err.strip():
            print(f"  STDERR: {err.strip()[:300]}")

    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()

    return True


def main():
    print("MCP Server Health Check")
    print("=" * 50)
    results = {}
    for name, binary in SERVERS.items():
        results[name] = test_server(name, binary)

    print(f"\n\n{'='*50}")
    print("SUMMARY")
    print(f"{'='*50}")
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"  {name:15s} [{status}]")

    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"\n  {passed}/{total} servers passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
