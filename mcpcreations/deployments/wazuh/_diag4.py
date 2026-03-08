#!/usr/bin/env python3
"""Check plugin i18n files and server logs for locale error source."""
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

# ── 1. Server startup logs — grep for i18n/locale errors ─────────────────────
print("=" * 60)
print("1. Server logs grep for i18n/locale")
print("=" * 60)
out = exec_in(base, tok, cid,
    "cat /proc/1/fd/1 2>/dev/null | grep -i 'i18n\\|locale' | head -20; "
    "echo '---'; "
    # Check if there are any error logs in the dashboard's log directory
    "find /usr/share/wazuh-dashboard -name '*.log' 2>/dev/null | xargs grep -l 'i18n\\|locale' 2>/dev/null | head -5",
    timeout=20)
print(out)

# ── 2. Check /translations/*.json endpoints available ────────────────────────
print("=" * 60)
print("2. Available translations endpoints (directory listing)")
print("=" * 60)
out = exec_in(base, tok, cid,
    "find /usr/share/wazuh-dashboard -path '*/translations/*.json' 2>/dev/null | head -20; "
    "echo '--- plugins translations ---'; "
    "find /usr/share/wazuh-dashboard/plugins -name 'en.json' 2>/dev/null | head -20",
    timeout=20)
print(out)

# ── 3. Check the Wazuh plugin translation files ───────────────────────────────
print("=" * 60)
print("3. Wazuh plugin i18n files (locale check)")
print("=" * 60)
out = exec_in(base, tok, cid,
    r"""find /usr/share/wazuh-dashboard/plugins -name '*.json' 2>/dev/null | xargs grep -l 'locale' 2>/dev/null | head -10 | while read f; do
    echo "=== $f ===";
    python3 -c "
import json, sys
try:
    data = json.load(open('$f'))
    print('locale:', data.get('locale', 'MISSING'))
    print('has messages:', 'messages' in data)
except Exception as e:
    print('Error:', e)
" 2>&1;
done""",
    timeout=30)
print(out)

# ── 4. Check what /translations/ routes are registered ───────────────────────
print("=" * 60)
print("4. All /translations/* requests the server handles")
print("=" * 60)
out = exec_in(base, tok, cid,
    "curl -sk http://localhost:5601/translations/ 2>&1 | head -c 300; echo; "
    "echo '---'; "
    "curl -sk -I http://localhost:5601/translations/en.json 2>&1 | head -20",
    timeout=15)
print(out)

# ── 5. Test from external URL (simulate what the browser does) ────────────────
print("=" * 60)
print("5. External URL: /translations/en.json via domain")
print("=" * 60)
import urllib.parse
ext_url = "https://wazuh.local.defaultvaluation.com"
try:
    req = urllib.request.Request(f"{ext_url}/translations/en.json",
        headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=ctx(), timeout=15) as resp:
        body = resp.read().decode()
        print(f"HTTP {resp.status}: {body[:300]}")
except Exception as e:
    print(f"Error: {e}")

# ── 6. Check server process arguments (is config really being passed?) ────────
print("=" * 60)
print("6. Server process cmdline and open files for config")
print("=" * 60)
out = exec_in(base, tok, cid,
    "cat /proc/1/cmdline 2>/dev/null | tr '\\0' ' '; echo; "
    "cat /proc/$(pgrep -f 'opensearch-dashboards' | head -1)/cmdline 2>/dev/null | tr '\\0' ' '; echo",
    timeout=15)
print(out)
