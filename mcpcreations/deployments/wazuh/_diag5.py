#!/usr/bin/env python3
"""Check plugin i18n files and container logs for locale error source."""
import json, ssl, struct, subprocess, urllib.request

EP = 2

def ks(a):
    return subprocess.run(
        ["security", "find-generic-password", "-s", "portainer-mcp", "-a", a, "-w"],
        capture_output=True, text=True).stdout.strip()

def ctx():
    c = ssl.create_default_context(); c.check_hostname = False; c.verify_mode = ssl.CERT_NONE; return c

def docker_raw(base, tok, path, timeout=30):
    r = urllib.request.Request(f"{base}/api/endpoints/{EP}/docker/{path}",
        headers={"X-API-Key": tok}, method="GET")
    with urllib.request.urlopen(r, context=ctx(), timeout=timeout) as resp:
        return resp.read()

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

# ── 1. Container logs (last 100 lines) grep for i18n/locale ──────────────────
print("=" * 60)
print("1. Container logs grep for i18n/locale/error")
print("=" * 60)
try:
    raw_logs = docker_raw(base, tok, f"containers/{cid}/logs?stdout=true&stderr=true&tail=200", timeout=20)
    logs_text = stream(raw_logs)
    matching = [l for l in logs_text.splitlines() if any(kw in l.lower() for kw in ["i18n","locale","error","warn","fatal"])]
    print(f"Total log lines: {len(logs_text.splitlines())}")
    print(f"Matching lines (i18n/locale/error/warn/fatal): {len(matching)}")
    for l in matching[:30]:
        print(l)
except Exception as e:
    print(f"Logs error: {e}")

# ── 2. List plugin translation files ─────────────────────────────────────────
print("=" * 60)
print("2. Plugin translation files (find en.json in plugins)")
print("=" * 60)
out = exec_in(base, tok, cid,
    "find /usr/share/wazuh-dashboard/plugins -name 'en.json' 2>/dev/null | head -20",
    timeout=20)
print(out if out.strip() else "NONE found")

# ── 3. Check each plugin translation file for locale field ───────────────────
print("=" * 60)
print("3. Plugin en.json locale values")
print("=" * 60)
out = exec_in(base, tok, cid,
    r"""find /usr/share/wazuh-dashboard/plugins -name 'en.json' 2>/dev/null | while read f; do
    loc=$(python3 -c "import json; d=json.load(open('$f')); print(repr(d.get('locale','MISSING')))" 2>&1)
    echo "$f -> locale=$loc"
done""",
    timeout=30)
print(out if out.strip() else "No plugin en.json files found")

# ── 4. External URL translations test ────────────────────────────────────────
print("=" * 60)
print("4. External URL /translations/en.json")
print("=" * 60)
ext_url = "https://wazuh.local.defaultvaluation.com"
try:
    req = urllib.request.Request(f"{ext_url}/translations/en.json",
        headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
    with urllib.request.urlopen(req, context=ctx(), timeout=8) as resp:
        body = resp.read().decode()
        print(f"HTTP {resp.status}: {body[:300]}")
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: {e.read()[:200]}")
except Exception as e:
    print(f"Error (may be DNS/network from local Mac): {type(e).__name__}: {e}")

# ── 5. External URL login page — check for translationsUrl ───────────────────
print("=" * 60)
print("5. External URL /app/login — verify translationsUrl")
print("=" * 60)
import re, html as hlib
try:
    req = urllib.request.Request(f"{ext_url}/app/login",
        headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"})
    with urllib.request.urlopen(req, context=ctx(), timeout=8) as resp:
        body = resp.read().decode("utf-8", "replace")
        print(f"HTTP {resp.status}, body length: {len(body)}")
        m = re.search(r'"i18n":\{"translationsUrl":"([^"]+)"', hlib.unescape(body))
        if m:
            print(f"translationsUrl: {m.group(1)}")
        else:
            print("translationsUrl NOT found in HTML (may need encoded search)")
            m2 = re.search(r'translationsUrl', body)
            print(f"Raw 'translationsUrl' present: {bool(m2)}")
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")

# ── 6. Server process cmdline ─────────────────────────────────────────────────
print("=" * 60)
print("6. Node.js process arguments")
print("=" * 60)
out = exec_in(base, tok, cid,
    "ps aux 2>/dev/null | grep -v grep | grep 'node\\|dashboard'; echo '---'; "
    "cat /proc/$(pgrep -f 'opensearch-dashboards' 2>/dev/null | head -1)/cmdline 2>/dev/null | tr '\\0' '\\n' | head -20",
    timeout=15)
print(out)
