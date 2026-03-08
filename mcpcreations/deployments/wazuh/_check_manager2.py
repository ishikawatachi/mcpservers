#!/usr/bin/env python3
"""Check manager 0-wazuh-init, look for wazuh template, check indexer indices."""
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
cs = docker(base, tok, "GET", "containers/json?all=true")
mgr = next((c for c in cs if "wazuh-manager" in ",".join(c.get("Names",[])) and c["State"] == "running"), None)
idx = next((c for c in cs if "wazuh-indexer" in ",".join(c.get("Names",[])) and c["State"] == "running"), None)

# ── 1. Read 0-wazuh-init script ───────────────────────────────────────────────
print("=" * 60)
print("1. 0-wazuh-init script (first 150 lines)")
print("=" * 60)
if mgr:
    out = exec_in(base, tok, mgr["Id"],
        "cat /var/run/s6/etc/cont-init.d/0-wazuh-init 2>/dev/null | head -150",
        timeout=15)
    print(out)

# ── 2. Search for wazuh-template.json anywhere in manager image ───────────────
print("=" * 60)
print("2. Any JSON template files in manager container")
print("=" * 60)
if mgr:
    out = exec_in(base, tok, mgr["Id"],
        "find /var/ossec /usr/share /opt -name '*template*' -o -name '*mapping*' "
        "2>/dev/null | grep -E '\\.(json|yml)$' | head -20",
        timeout=20)
    print(out if out.strip() else "NONE found")

# ── 3. Check Wazuh Filebeat module installation ───────────────────────────────
print("=" * 60)
print("3. Wazuh Filebeat module directory")
print("=" * 60)
if mgr:
    out = exec_in(base, tok, mgr["Id"],
        "ls -la /usr/share/filebeat/module/ 2>/dev/null | head -30; "
        "echo '---'; "
        "ls /usr/share/filebeat/module/wazuh/ 2>/dev/null || echo 'NO wazuh module'",
        timeout=15)
    print(out)

# ── 4. Check indexer for Wazuh indices ───────────────────────────────────────
print("=" * 60)
print("4. OpenSearch existing indices (wazuh-*)")
print("=" * 60)
if idx:
    out = exec_in(base, tok, idx["Id"],
        "curl -sk -u 'admin:Wazuh!!Wazuh!!' https://localhost:9200/_cat/indices?v 2>&1 | head -30",
        timeout=15)
    print(out)

# ── 5. Check /var/ossec for filebeat config ───────────────────────────────────
print("=" * 60)
print("5. /var/ossec contents (check for filebeat-related files)")
print("=" * 60)
if mgr:
    out = exec_in(base, tok, mgr["Id"],
        "ls -la /var/ossec/ 2>&1 | head -30; "
        "echo '---'; "
        "find /var/ossec -name '*filebeat*' -o -name '*template*' 2>/dev/null | head -10",
        timeout=15)
    print(out)
