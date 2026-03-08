#!/usr/bin/env python3
"""Update internal_users.yml with correct password hash, then re-apply security config."""
import base64, json, ssl, struct, subprocess, urllib.request

EP = 2
NEW_HASH = "$2y$12$avBe8VX7tup/nixYvLRB..DOl3/fI7I61.bIRkJIKhVBkW3tje162"

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

# Python code that runs inside the container to update internal_users.yml
py_src = r"""
import os, re
IU = '/usr/share/wazuh-indexer/opensearch-security/internal_users.yml'
h = os.environ['NEW_HASH']
txt = open(IU).read()
# Replace hash for each user (YAML: "  hash: "..."\n")
for user in ('admin', 'kibanaserver'):
    txt = re.sub(
        r'(^' + user + r':.*?(?:\n  \S.*?)*?\n  hash:) "([^"]+)"',
        r'\1 "' + h + '"',
        txt, flags=re.MULTILINE
    )
open(IU, 'w').write(txt)
print('Updated', IU)
for line in open(IU):
    if line.strip().startswith('hash:'):
        print(' ', line.rstrip())
"""
encoded = base64.b64encode(py_src.encode()).decode()

base2 = ks("portainer-url"); tok2 = ks("portainer-token")
cs2 = api(base2, tok2, "GET", "containers/json?all=true")
for c in cs2:
    names = ",".join(c.get("Names",[]))
    if "wazuh" in names.lower():
        print(f"{names}: {c['Status']}  id={c['Id'][:12]}")
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
