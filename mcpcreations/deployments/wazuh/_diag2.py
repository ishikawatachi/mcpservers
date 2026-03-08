#!/usr/bin/env python3
"""Deep diagnostic: get raw HTML and full entrypoint to find i18n root cause."""
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
dash = next((c for c in cs if "wazuh-dashboard" in ",".join(c.get("Names",[])) and c["State"] == "running"), None)
if not dash:
    print("ERROR: dashboard not running"); exit(1)
cid = dash["Id"]
print(f"Dashboard: {cid[:12]}\n")

# ── 1. First 3000 chars of /app/login HTML ───────────────────────────────────
print("=" * 60)
print("1. Raw HTML of /app/login (first 3000 chars)")
print("=" * 60)
out = exec_in(base, tok, cid,
    "curl -sk http://localhost:5601/app/login 2>&1 | head -c 3000", timeout=20)
print(out)

# ── 2. Search for locale in different formats ─────────────────────────────────
print("=" * 60)
print("2. Grep for 'locale' anywhere in the login page HTML")
print("=" * 60)
out = exec_in(base, tok, cid,
    "curl -sk http://localhost:5601/app/login 2>&1 | grep -oi 'locale[^\"]*\"[^\"]*\"' | head -10; "
    "echo '---'; "
    "curl -sk http://localhost:5601/app/login 2>&1 | grep -c 'locale' || echo '0 matches'",
    timeout=20)
print(out)

# ── 3. Full /entrypoint.sh ────────────────────────────────────────────────────
print("=" * 60)
print("3. Full /entrypoint.sh")
print("=" * 60)
out = exec_in(base, tok, cid, "cat /entrypoint.sh 2>&1", timeout=15)
print(out)

# ── 4. Check all *.sh scripts that touch config ───────────────────────────────
print("=" * 60)
print("4. Scripts that reference opensearch_dashboards or YML")
print("=" * 60)
out = exec_in(base, tok, cid,
    "find /usr/share/wazuh-dashboard -name '*.sh' 2>/dev/null | xargs grep -l 'opensearch_dashboards\\|i18n' 2>/dev/null | head -10; "
    "echo '---'; "
    "find / -maxdepth 3 -name '*.sh' 2>/dev/null | xargs grep -l 'i18n\\|locale' 2>/dev/null | head -10",
    timeout=20)
print(out)

# ── 5. Check the translations endpoint content ────────────────────────────────
print("=" * 60)
print("5. /translations/en.json (first 300 chars)")
print("=" * 60)
out = exec_in(base, tok, cid,
    "curl -sk http://localhost:5601/translations/en.json 2>&1 | head -c 300",
    timeout=15)
print(out)
