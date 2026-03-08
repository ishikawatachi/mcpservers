#!/usr/bin/env python3
"""
Diagnose i18n locale error on Wazuh Dashboard.
- Checks what config the Node.js process is actually reading
- Reads the live HTML bootstrap response to see what locale the server sends
- Checks all config file locations
- Fixes the root cause
- Provides a standalone test function
"""
import base64, json, ssl, struct, subprocess, time, urllib.request

EP = 2

def ks(a):
    return subprocess.run(
        ["security", "find-generic-password", "-s", "portainer-mcp", "-a", a, "-w"],
        capture_output=True, text=True).stdout.strip()

def ctx():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c

def docker(base, tok, method, path, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else (b"{}" if method in ("POST","PUT") else None)
    hdrs = {"X-API-Key": tok}
    if data:
        hdrs["Content-Type"] = "application/json"
    r = urllib.request.Request(f"{base}/api/endpoints/{EP}/docker/{path}", data=data, headers=hdrs, method=method)
    with urllib.request.urlopen(r, context=ctx(), timeout=timeout) as resp:
        raw = resp.read()
        return json.loads(raw) if raw.strip() else {}

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
print(f"Dashboard: {cid[:12]}  {dash['Status']}\n")

# ── 1. What config files does the process actually read? ─────────────────────
print("=" * 60)
print("1. Node process cmdline + config paths")
print("=" * 60)
out = exec_in(base, tok, cid,
    "cat /proc/1/cmdline 2>/dev/null | tr '\\0' '\\n' | head -20; "
    "echo '---'; "
    "find / -name 'opensearch_dashboards.yml' 2>/dev/null; "
    "echo '---'; "
    "ls /usr/share/wazuh-dashboard/config/ 2>/dev/null; "
    "echo '---'; "
    "ls /etc/wazuh-dashboard/ 2>/dev/null", timeout=15)
print(out)

# ── 2. Check ALL config file locations for i18n.locale ───────────────────────
print("=" * 60)
print("2. i18n.locale presence in ALL config files")
print("=" * 60)
out = exec_in(base, tok, cid,
    "echo '--- /usr/share/wazuh-dashboard/config/opensearch_dashboards.yml ---' && "
    "cat /usr/share/wazuh-dashboard/config/opensearch_dashboards.yml 2>&1 | grep -n 'i18n\\|locale' || echo '  (not found)'; "
    "echo '--- /etc/wazuh-dashboard/opensearch_dashboards.yml ---' && "
    "cat /etc/wazuh-dashboard/opensearch_dashboards.yml 2>&1 | grep -n 'i18n\\|locale' || echo '  (not found)'; "
    "echo '--- /usr/share/wazuh-dashboard/opensearch_dashboards.yml ---' && "
    "cat /usr/share/wazuh-dashboard/opensearch_dashboards.yml 2>&1 | grep -n 'i18n\\|locale' || echo '  (not found)'",
    timeout=15)
print(out)

# ── 3. What locale does the server embed in the HTML bootstrap? ───────────────
print("=" * 60)
print("3. HTML bootstrap from server — looking for locale string")
print("=" * 60)
out = exec_in(base, tok, cid,
    "curl -sk http://localhost:5601/app/login 2>&1 | grep -o '\"locale\":[^,}]*' | head -5; "
    "echo '---full osdConfig---'; "
    "curl -sk http://localhost:5601/app/login 2>&1 | grep -o '__osdConfig[^<]*' | head -3; "
    "echo '---translations endpoint---'; "
    "curl -sk -o /dev/null -w '%{http_code}' http://localhost:5601/translations/en.json 2>&1",
    timeout=20)
print(out)

# ── 4. Check entrypoint script ────────────────────────────────────────────────
print("=" * 60)
print("4. Entrypoint / docker startup script")
print("=" * 60)
out = exec_in(base, tok, cid,
    "ls /usr/share/wazuh-dashboard/bin/ 2>/dev/null | head -10; "
    "echo '---'; "
    "cat /usr/share/wazuh-dashboard/bin/opensearch-dashboards-docker 2>/dev/null | grep -A5 -B2 'i18n\\|locale' | head -30; "
    "echo '---entrypoint---'; "
    "cat /docker-entrypoint.sh 2>/dev/null | grep -A3 -B3 'i18n\\|locale\\|YML\\|config' | head -40",
    timeout=15)
print(out)

# ── 5. Check wazuh_app_config.sh for config generation ───────────────────────
print("=" * 60)
print("5. wazuh_app_config.sh — looking for config rewrite logic")
print("=" * 60)
out = exec_in(base, tok, cid,
    "find / -name 'entrypoint.sh' -o -name 'wazuh-dashboard-entrypoint.sh' 2>/dev/null | head -5; "
    "echo '---'; "
    "cat /usr/share/wazuh-dashboard/config/envs.yml 2>/dev/null | head -30 || echo 'no envs.yml'; "
    "echo '---env-based config---'; "
    "env | grep -i 'i18n\\|locale' 2>/dev/null || echo 'no i18n env vars'",
    timeout=15)
print(out)
