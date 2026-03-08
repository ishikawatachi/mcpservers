#!/usr/bin/env python3
"""Check wazuh-indexer health and wazuh-manager logs."""
import json, ssl, struct, subprocess, urllib.request

EP = 2
INDEXER_PASS = "Wazuh!!Wazuh!!"
INDEXER_USER = "admin"

def ks(a):
    return subprocess.run(
        ["security", "find-generic-password", "-s", "portainer-mcp", "-a", a, "-w"],
        capture_output=True, text=True).stdout.strip()

def ctx():
    c = ssl.create_default_context(); c.check_hostname = False; c.verify_mode = ssl.CERT_NONE; return c

def docker(base, tok, method, path, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else (b"{}" if method in ("POST","PUT") else None)
    hdrs = {"X-API-Key": tok}
    if data: hdrs["Content-Type"] = "application/json"
    r = urllib.request.Request(f"{base}/api/endpoints/{EP}/docker/{path}", data=data, headers=hdrs, method=method)
    with urllib.request.urlopen(r, context=ctx(), timeout=timeout) as resp:
        raw = resp.read(); return json.loads(raw) if raw.strip() else {}

def stream(raw):
    i = 0; parts = []
    while i + 8 <= len(raw):
        sz = struct.unpack(">I", raw[i+4:i+8])[0]; i += 8
        if i + sz <= len(raw): parts.append(raw[i:i+sz].decode("utf-8","replace"))
        i += sz
    return "".join(parts)

def exec_in(base, tok, cid, cmd, timeout=30):
    er = docker(base, tok, "POST", f"containers/{cid}/exec", {
        "AttachStdout": True, "AttachStderr": True, "Tty": False,
        "Cmd": ["/bin/sh", "-c", cmd]
    })
    r = urllib.request.Request(
        f"{base}/api/endpoints/{EP}/docker/exec/{er['Id']}/start",
        data=json.dumps({"Detach": False, "Tty": False}).encode(),
        headers={"X-API-Key": tok, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(r, context=ctx(), timeout=timeout) as resp:
        return stream(resp.read())

def get_logs(base, tok, cid, tail=100):
    r = urllib.request.Request(
        f"{base}/api/endpoints/{EP}/docker/containers/{cid}/logs?stdout=true&stderr=true&tail={tail}",
        headers={"X-API-Key": tok}, method="GET")
    with urllib.request.urlopen(r, context=ctx(), timeout=30) as resp:
        return stream(resp.read())

base = ks("portainer-url"); tok = ks("portainer-token")
cs = docker(base, tok, "GET", "containers/json?all=true")

mgr = next((c for c in cs if "wazuh-manager" in ",".join(c.get("Names",[])) and c["State"] == "running"), None)
idx = next((c for c in cs if "wazuh-indexer" in ",".join(c.get("Names",[])) and c["State"] == "running"), None)

# ── 1. Container restart counts ───────────────────────────────────────────────
print("=" * 60)
print("1. Container restart counts")
print("=" * 60)
for c in cs:
    names = ",".join(c.get("Names", []))
    if "wazuh" in names.lower():
        detail = docker(base, tok, "GET", f"containers/{c['Id']}/json")
        restarts = detail.get("RestartCount", 0)
        status = c.get("Status", "")
        print(f"  {names}: restarts={restarts}, status={status}")

# ── 2. Wazuh indexer cluster health ──────────────────────────────────────────
print("\n" + "=" * 60)
print("2. Wazuh indexer cluster health")
print("=" * 60)
if idx:
    import base64 as b64
    auth = b64.b64encode(f"{INDEXER_USER}:{INDEXER_PASS}".encode()).decode()
    out = exec_in(base, tok, idx["Id"],
        f'curl -sk -u "{INDEXER_USER}:{INDEXER_PASS}" https://localhost:9200/_cluster/health?pretty 2>&1',
        timeout=15)
    print(out)
else:
    print("Indexer not running")

# ── 3. Wazuh indexer last logs (errors) ──────────────────────────────────────
print("=" * 60)
print("3. Wazuh indexer recent logs (last 50 lines, errors/warn only)")
print("=" * 60)
if idx:
    logs = get_logs(base, tok, idx["Id"], tail=50)
    for line in logs.splitlines():
        if any(kw in line.lower() for kw in ["error","warn","exception","fail","fatal"]):
            print(line)
    if not any(any(kw in line.lower() for kw in ["error","warn","exception","fail","fatal"]) for line in logs.splitlines()):
        print("(no error/warn lines in last 50 log lines)")
        print("Last 10 lines:")
        for l in logs.splitlines()[-10:]:
            print(l)
else:
    print("Indexer not running")

# ── 4. Wazuh indexer healthcheck ─────────────────────────────────────────────
print("=" * 60)
print("4. Indexer container healthcheck config and last result")
print("=" * 60)
if idx:
    detail = docker(base, tok, "GET", f"containers/{idx['Id']}/json")
    health = detail.get("State", {}).get("Health", {})
    print(f"Status: {health.get('Status')}")
    print(f"FailingStreak: {health.get('FailingStreak')}")
    logs_h = health.get("Log", [])
    for entry in logs_h[-3:]:
        print(f"  ExitCode={entry.get('ExitCode')} Output={entry.get('Output','')[:200]}")

# ── 5. Wazuh manager recent logs ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("5. Wazuh manager recent logs (last 50 lines)")
print("=" * 60)
if mgr:
    logs = get_logs(base, tok, mgr["Id"], tail=50)
    print(logs[-3000:] if len(logs) > 3000 else logs)
else:
    print("Manager not running")

# ── 6. Wazuh manager current state ───────────────────────────────────────────
print("=" * 60)
print("6. Wazuh manager current state")
print("=" * 60)
if mgr:
    detail = docker(base, tok, "GET", f"containers/{mgr['Id']}/json")
    state = detail.get("State", {})
    print(f"Status: {state.get('Status')}")
    print(f"Running: {state.get('Running')}")
    print(f"StartedAt: {state.get('StartedAt')}")
    print(f"RestartCount: {detail.get('RestartCount', 0)}")
    health = state.get("Health", {})
    if health:
        print(f"Health.Status: {health.get('Status')}")
        for entry in health.get("Log", [])[-2:]:
            print(f"  HC ExitCode={entry.get('ExitCode')} Output={entry.get('Output','')[:200]}")
