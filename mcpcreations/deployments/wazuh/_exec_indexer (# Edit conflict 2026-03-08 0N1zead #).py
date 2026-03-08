#!/usr/bin/env python3
"""Exec inside wazuh-indexer to check process list and port 9200."""
import json, ssl, subprocess, urllib.request

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

cmd = ("export OPENSEARCH_JAVA_HOME=/usr/share/wazuh-indexer/jdk && "
       "/usr/share/wazuh-indexer/plugins/opensearch-security/tools/securityadmin.sh "
       "-cd /usr/share/wazuh-indexer/opensearch-security/ "
       "-cacert /usr/share/wazuh-indexer/certs/root-ca.pem "
       "-cert /usr/share/wazuh-indexer/certs/admin.pem "
       "-key /usr/share/wazuh-indexer/certs/admin-key.pem "
       "-h wazuh.indexer -p 9200 -nhnv 2>&1 | tail -30")

exec_resp = api(base, tok, "POST", f"containers/{cid}/exec", {
    "AttachStdout": True, "AttachStderr": True, "Tty": False,
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

lines = []
for line in out.split(b"\n"):
    if len(line) > 8: line = line[8:]
    lines.append(line.decode("utf-8","replace"))
print("\n".join(lines))
