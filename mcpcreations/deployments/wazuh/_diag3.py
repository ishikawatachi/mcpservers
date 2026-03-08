#!/usr/bin/env python3
"""Targeted diagnostic: read wazuh_app_config.sh + find translationsUrl in HTML."""
import json, ssl, struct, subprocess, urllib.request, html

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

# ── 1. Read /wazuh_app_config.sh ─────────────────────────────────────────────
print("=" * 60)
print("1. /wazuh_app_config.sh (full)")
print("=" * 60)
out = exec_in(base, tok, cid, "cat /wazuh_app_config.sh 2>&1", timeout=15)
print(out)

# ── 2. Extract i18n section from the injected metadata ───────────────────────
print("=" * 60)
print("2. i18n / translationsUrl in the injected metadata (full HTML)")
print("=" * 60)
out = exec_in(base, tok, cid,
    # Get full HTML and search for translationsUrl and i18n key
    r"""curl -sk http://localhost:5601/app/login 2>&1 | python3 -c "
import sys, re, html as h
content = sys.stdin.read()
# Search for translationsUrl
m = re.search(r'translationsUrl[^&\"<]{0,200}', content)
if m: print('translationsUrl match:', m.group(0)[:200])
else: print('NO translationsUrl found in HTML')
# Search for i18n key  
m2 = re.search(r'(&quot;|.)i18n(&quot;|.).*?(&gt;|>)', content[:50000])
if m2: print('i18n match:', h.unescape(m2.group(0))[:300])
else: print('NO i18n key found in HTML')
# Grep for translations in the raw content
matches = re.findall(r'translation[^&]{0,100}', content)
print('translation fragments:', matches[:5] if matches else 'NONE')
" 2>&1""",
    timeout=30)
print(out)

# ── 3. Parse osd-injected-metadata and show i18n section ─────────────────────
print("=" * 60)
print("3. Parse osd-injected-metadata params (JSON → i18n section)")
print("=" * 60)
out = exec_in(base, tok, cid,
    r"""curl -sk http://localhost:5601/app/login 2>&1 | python3 -c "
import sys, re, json, html as h

content = sys.stdin.read()
# Find osd-injected-metadata params='...'  (single-quoted attribute)
m = re.search(r'osd-injected-metadata params=\'(.*?)\'><', content, re.DOTALL)
if not m:
    m = re.search(r'osd-injected-metadata params=\"(.*?)\">', content, re.DOTALL)
if not m:
    print('ERROR: osd-injected-metadata not found'); sys.exit(1)

raw = h.unescape(m.group(1))
try:
    data = json.loads(raw)
except Exception as e:
    print('JSON parse error:', e)
    print('Raw first 500:', raw[:500])
    sys.exit(1)

print('Top-level keys:', list(data.keys()))
print()
if 'i18n' in data:
    print('i18n section:', json.dumps(data['i18n'], indent=2))
else:
    print('ERROR: No i18n section in injected metadata!')
print()
if 'legacyMetadata' in data:
    lm = data['legacyMetadata']
    print('legacyMetadata keys:', list(lm.keys()))
" 2>&1""",
    timeout=30)
print(out)

# ── 4. Test the /translations/ endpoint with empty and 'en' locale ───────────
print("=" * 60)
print("4. Test /translations/ endpoints")
print("=" * 60)
out = exec_in(base, tok, cid,
    "echo '-- /translations/en.json --'; "
    "curl -sk http://localhost:5601/translations/en.json 2>&1 | head -c 200; echo; "
    "echo '-- /translations/.json --'; "
    "curl -sk http://localhost:5601/translations/.json 2>&1 | head -c 200; echo; "
    "echo '-- /translations/undefined.json --'; "
    "curl -sk http://localhost:5601/translations/undefined.json 2>&1 | head -c 200; echo",
    timeout=20)
print(out)

# ── 5. Check the actual config the process is using ──────────────────────────
print("=" * 60)
print("5. Config file content (cat full file)")
print("=" * 60)
out = exec_in(base, tok, cid,
    "cat -A /usr/share/wazuh-dashboard/config/opensearch_dashboards.yml 2>&1",
    timeout=15)
print(out)
