#!/usr/bin/env python3
"""Final health check: show container states and indexer cluster health."""
import json, subprocess, ssl, urllib.request

def ks(a):
    return subprocess.run(
        ["security","find-generic-password","-s","portainer-mcp","-a",a,"-w"],
        capture_output=True, text=True).stdout.strip()

def ssl_ctx():
    c = ssl.create_default_context(); c.check_hostname = False; c.verify_mode = ssl.CERT_NONE; return c

def api(base, tok, path):
    r = urllib.request.Request(f"{base}/api/{path}", headers={"X-API-Key": tok})
    with urllib.request.urlopen(r, context=ssl_ctx(), timeout=20) as resp:
        return json.loads(resp.read())

def docker(base, tok, ep, method, path, body=None, timeout=30):
    url = f"{base}/api/endpoints/{ep}/docker/{path}"
    data = json.dumps(body).encode() if body else None
    headers = {"X-API-Key": tok}
    if data:
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    with urllib.request.urlopen(r, context=ssl_ctx(), timeout=timeout) as resp:
        raw = resp.read()
        return json.loads(raw) if raw.strip() else {}

def exec_in(base, tok, ep, cid, cmd, timeout=30):
    exec_id = docker(base, tok, ep, "POST", f"containers/{cid}/exec", {
        "AttachStdout": True, "AttachStderr": True,
        "Cmd": ["/bin/sh", "-c", cmd]
    })["Id"]
    r = urllib.request.Request(f"{base}/api/endpoints/{ep}/docker/exec/{exec_id}/start",
        data=b'{"Detach":false,"Tty":false}',
        headers={"X-API-Key": tok, "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(r, context=ssl_ctx(), timeout=timeout) as resp:
        raw = resp.read()
    # strip Docker multiplexed stream header (8 bytes per frame)
    out = b""
    i = 0
    while i + 8 <= len(raw):
        frame_len = int.from_bytes(raw[i+4:i+8], "big")
        out += raw[i+8:i+8+frame_len]
        i += 8 + frame_len
    return out.decode(errors="replace").strip()

base = ks("portainer-url"); tok = ks("portainer-token"); EP = 2

# List all containers
containers = docker(base, tok, EP, "GET", "containers/json?all=1")
wazuh = [c for c in containers if any("wazuh" in n for n in c.get("Names", []))]

print("=== Container health ===")
for c in sorted(wazuh, key=lambda x: x["Names"][0]):
    name = c["Names"][0].lstrip("/")
    status = c.get("Status", "?")
    restarts = c.get("HostConfig", {}).get("RestartCount", "?")
    hc = c.get("State", "?")
    print(f"  {name:30s}  {status}")

# Find indexer and manager containers
indexer = next((c for c in wazuh if "indexer" in c["Names"][0]), None)
manager = next((c for c in wazuh if "manager" in c["Names"][0]), None)

if indexer:
    print(f"\n=== Indexer cluster health ===")
    out = exec_in(base, tok, EP, indexer["Id"],
        "curl -sk -u admin:${INDEXER_PASSWORD:-Wazuh!!Wazuh!!} https://localhost:9200/_cluster/health | python3 -m json.tool 2>/dev/null || curl -sk -u admin:'Wazuh!!Wazuh!!' https://localhost:9200/_cluster/health")
    print(out[:600])

if manager:
    print(f"\n=== Manager API (port 55000) ===")
    out = exec_in(base, tok, EP, manager["Id"],
        "curl -sk https://localhost:55000/ 2>&1 | head -3")
    print(out[:200])
    
    print(f"\n=== Manager restart count ===")
    info = docker(base, tok, EP, "GET", f"containers/{manager['Id']}/json")
    print(f"  RestartCount={info.get('RestartCount', '?')}  Status={info.get('State', {}).get('Status', '?')}")
    hc = info.get("State", {}).get("Health", {})
    if hc:
        print(f"  Health={hc.get('Status','?')}  FailingStreak={hc.get('FailingStreak','?')}")
        last = hc.get("Log", [])
        if last:
            print(f"  LastCheck: exit={last[-1].get('ExitCode','?')} output={last[-1].get('Output','').strip()[:100]}")

print("\n=== UI Test ===")
import importlib.util, sys, os, urllib.request
spec = importlib.util.spec_from_file_location("test_ui",
    os.path.join(os.path.dirname(__file__), "_test_wazuh_ui.py"))
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
except SystemExit:
    pass
