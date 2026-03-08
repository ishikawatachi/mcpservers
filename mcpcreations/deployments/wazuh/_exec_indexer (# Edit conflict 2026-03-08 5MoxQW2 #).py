#!/usr/bin/env python3
"""Exec inside wazuh-indexer to check process list and port 9200."""
import json, ssl, struct, subprocess, urllib.request

EP = 2

def ks(a): return subprocess.run(["security","find-generic-password","-s","portainer-mcp","-a",a,"-w"], capture_output=True, text=True).stdout.strip()
def ctx():
    c = ssl.create_default_context(); c.check_hostname = False; c.verify_mode = ssl.CERT_NONE; return c
def api(base, tok, method, path, body=None, timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    if data is None and method in ("POST","PUT"): data = b""
    hdrs = {"X-API-Key": tok}
    if data: hdrs["Content-Type"] = "application/json"
    r = urllib.request.Request(f"{base}/api/endpoints/{EP}/docker/{path}", data=data, headers=hdrs, method=method)
    with urllib.request.urlopen(r, context=ctx(), timeout=timeout) as resp:
        raw = resp.read(); return json.loads(raw) if raw.strip() else {}

base = ks("portainer-url"); tok = ks("portainer-token")
cs = api(base, tok, "GET", "containers/json?all=true")
indexer = next((c for c in cs if "wazuh-indexer" in ",".join(c.get("Names",[])) and c.get("State")=="running"), None)
if not indexer:
    print("wazuh-indexer NOT running"); exit(1)
cid = indexer["Id"]
print(f"Indexer: {cid[:12]}  {indexer['Status']}")

NEW_HASH = "$2y$12$avBe8VX7tup/nixYvLRB..DOl3/fI7I61.bIRkJIKhVBkW3tje162"

py_code = r"""
import os, re, subprocess
IU = '/usr/share/wazuh-indexer/opensearch-security/internal_users.yml'
h = os.environ['NEW_HASH']
txt = open(IU).read()
# Replace hash values for admin and kibanaserver
def replace_hash(user, content, newhash):
    return re.sub(
        r'(' + re.escape(user) + r':\n  hash:) "([^"]+)"',
        r'\1 "' + newhash + '"',
        content
    )
txt = replace_hash('admin', txt, h)
txt = replace_hash('kibanaserver', txt, h)
open(IU, 'w').write(txt)
print('internal_users.yml updated')
# Verify
for line in open(IU):
    if 'hash' in line and ('admin' in line or line.strip().startswith('hash')):
        print(repr(line.rstrip()))
"""

# Run Python to update the file, then securityadmin
cmd = (
    f'python3 -c {repr(py_code)} && '
    'echo "---running securityadmin---" && '
    'OPENSEARCH_JAVA_HOME=/usr/share/wazuh-indexer/jdk '
    '/usr/share/wazuh-indexer/plugins/opensearch-security/tools/securityadmin.sh '
    '-f /usr/share/wazuh-indexer/opensearch-security/internal_users.yml '
    '-t internalusers '
    '-icl -nhnv '
    '-cacert /usr/share/wazuh-indexer/certs/root-ca.pem '
    '-cert /usr/share/wazuh-indexer/certs/admin.pem '
    '-key /usr/share/wazuh-indexer/certs/admin-key.pem '
    '-h wazuh.indexer -p 9200 2>&1'
)

exec_resp = api(base, tok, "POST", f"containers/{cid}/exec", {
    "AttachStdout": True, "AttachStderr": True, "Tty": False,
    "Env": [f"PASS=Wazuh!!Wazuh!!", f"NEW_HASH={NEW_HASH}"],
    "Cmd": ["sh", "-c", cmd]
})
eid = exec_resp.get("Id","")
print(f"Exec: {eid[:12]}")
data = json.dumps({"Detach": False, "Tty": False}).encode()
r = urllib.request.Request(f"{base}/api/endpoints/{EP}/docker/exec/{eid}/start",
    data=data, headers={"X-API-Key": tok, "Content-Type": "application/json"}, method="POST")
try:
    with urllib.request.urlopen(r, context=ctx(), timeout=120) as resp:
        out = resp.read()
except Exception as e:
    print(f"Exec error: {e}"); exit(1)

# Parse Docker multiplexed stream: 8-byte header per frame (1B type, 3B reserved, 4B size)
decoded = []
i = 0
while i + 8 <= len(out):
    size = struct.unpack(">I", out[i+4:i+8])[0]
    i += 8
    if i + size <= len(out):
        decoded.append(out[i:i+size].decode("utf-8", "replace"))
    i += size
print("".join(decoded))
print(f"--- raw bytes ({len(out)}): {out[:200]!r}")
