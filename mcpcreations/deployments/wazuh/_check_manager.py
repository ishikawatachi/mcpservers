#!/usr/bin/env python3
"""Check Wazuh manager API and keystore permission issue."""
import json, ssl, struct, subprocess, urllib.request

EP = 2

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

base = ks("portainer-url"); tok = ks("portainer-token")

# ── 1. List all wazuh containers ─────────────────────────────────────────────
print("=" * 60)
print("1. All Wazuh containers status")
print("=" * 60)
cs = docker(base, tok, "GET", "containers/json?all=true")
for c in cs:
    names = ",".join(c.get("Names", []))
    if "wazuh" in names.lower():
        print(f"  {c['Id'][:12]}  state={c['State']:<8}  status={c['Status']:<30}  name={names}")

# ── 2. Get wazuh-manager container ID ────────────────────────────────────────
mgr = next((c for c in cs if "wazuh-manager" in ",".join(c.get("Names",[])) and c["State"] == "running"), None)
dash = next((c for c in cs if "wazuh-dashboard" in ",".join(c.get("Names",[])) and c["State"] == "running"), None)

if not mgr:
    print("\nERROR: wazuh-manager not running")
else:
    cid_mgr = mgr["Id"]
    print(f"\nManager: {cid_mgr[:12]}")

    # ── 3. Check if wazuh API is listening on port 55000 ─────────────────────
    print("\n" + "=" * 60)
    print("3. Wazuh manager port 55000 status (inside manager container)")
    print("=" * 60)
    out = exec_in(base, tok, cid_mgr,
        "ss -tlnp 2>/dev/null | grep 55000 || netstat -tlnp 2>/dev/null | grep 55000 || "
        "echo 'no ss/netstat, trying nc:'; nc -z localhost 55000 && echo 'port open' || echo 'port closed'",
        timeout=15)
    print(out)

    # ── 4. Check wazuh-manager API service ───────────────────────────────────
    print("=" * 60)
    print("4. Wazuh manager API curl test (inside manager)")
    print("=" * 60)
    out = exec_in(base, tok, cid_mgr,
        "curl -sk https://localhost:55000/ 2>&1 | head -c 300; echo",
        timeout=15)
    print(out)

    # ── 5. Wazuh manager services status ─────────────────────────────────────
    print("=" * 60)
    print("5. Wazuh manager process status")
    print("=" * 60)
    out = exec_in(base, tok, cid_mgr,
        "ps aux 2>/dev/null | grep -E 'wazuh|python|api' | grep -v grep | head -20",
        timeout=15)
    print(out)

# ── 6. Test from dashboard container: can it reach manager? ───────────────────
if dash:
    cid = dash["Id"]
    print("\n" + "=" * 60)
    print("6. Dashboard → Manager connectivity test")
    print("=" * 60)
    out = exec_in(base, tok, cid,
        "curl -sk --max-time 5 https://wazuh.manager:55000/ 2>&1 | head -c 300; echo",
        timeout=20)
    print(out)

    # ── 7. Keystore permission issue ──────────────────────────────────────────
    print("=" * 60)
    print("7. Keystore permission analysis")
    print("=" * 60)
    out = exec_in(base, tok, cid,
        "ls -la /etc/wazuh-dashboard/ 2>&1; echo '---'; "
        "ls -la /etc/wazuh-dashboard/opensearch_dashboards.keystore 2>/dev/null || echo 'keystore does not exist'; "
        "echo '---'; "
        "stat /etc/wazuh-dashboard/ 2>&1 | head -5",
        timeout=15)
    print(out)
