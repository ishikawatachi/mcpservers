#!/usr/bin/env python3
"""Append i18n.locale: en to opensearch_dashboards.yml and restart dashboard."""
import json, ssl, struct, subprocess, time, urllib.request

EP = 2

def ks(a):
    return subprocess.run(["security","find-generic-password","-s","portainer-mcp","-a",a,"-w"],
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

def stream(out):
    i = 0; parts = []
    while i + 8 <= len(out):
        sz = struct.unpack(">I", out[i+4:i+8])[0]; i += 8
        if i + sz <= len(out): parts.append(out[i:i+sz].decode("utf-8","replace"))
        i += sz
    return "".join(parts)

base = ks("portainer-url"); tok = ks("portainer-token")

# Step 1: append i18n.locale to the config file on host volume
name = "wazuh-fix-i18n"
try: docker(base, tok, "DELETE", f"containers/{name}?force=true")
except: pass

# Check if already set, only append if not
cmd = 'grep -q "i18n.locale" /t/opensearch_dashboards.yml && echo "already set" || (printf \'\\ni18n.locale: "en"\\n\' >> /t/opensearch_dashboards.yml && echo "appended")'

resp = docker(base, tok, "POST", f"containers/create?name={name}", {
    "Image": "wazuh/wazuh-dashboard:4.9.2",
    "User": "root",
    "Entrypoint": ["/bin/sh"],
    "Cmd": ["-c", cmd],
    "HostConfig": {"Binds": ["/volume1/docker/wazuh/wazuh-dashboard:/t"], "AutoRemove": False}
})
cid = resp["Id"]; print(f"Helper container: {cid[:12]}")
docker(base, tok, "POST", f"containers/{cid}/start", body={})

# Poll until exited
for _ in range(15):
    import time; time.sleep(1)
    info = docker(base, tok, "GET", f"containers/{cid}/json")
    if info.get("State",{}).get("Status") == "exited":
        break

r = urllib.request.Request(f"{base}/api/endpoints/{EP}/docker/containers/{cid}/logs?stdout=1&stderr=1&tail=10",
    headers={"X-API-Key": tok})
with urllib.request.urlopen(r, context=ctx(), timeout=15) as resp: out = resp.read()
result = stream(out).strip()
print(f"Result: {result}")
try: docker(base, tok, "DELETE", f"containers/{cid}?force=true")
except: pass

# Step 2: restart the dashboard
print("\nRestarting dashboard...")
cs = docker(base, tok, "GET", "containers/json?all=true")
dash = next((c for c in cs if "wazuh-dashboard" in ",".join(c.get("Names",[]))), None)
if dash:
    print(f"Dashboard: {dash['Id'][:12]}  {dash['Status']}")
    docker(base, tok, "POST", f"containers/{dash['Id']}/restart", body={}, timeout=60)
    print("Restart sent. Wait ~30s then reload https://wazuh.local.defaultvaluation.com")
else:
    print("Dashboard container not found")

import json, ssl, subprocess, urllib.request, time

EP = 2
def ks(a): return subprocess.run(["security","find-generic-password","-s","portainer-mcp","-a",a,"-w"], capture_output=True, text=True).stdout.strip()
def ctx():
    c = ssl.create_default_context(); c.check_hostname=False; c.verify_mode=ssl.CERT_NONE; return c
def api(base, tok, method, path, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    if data is None and method in ("POST","PUT"): data = b""
    hdrs = {"X-API-Key": tok}
    if data: hdrs["Content-Type"] = "application/json"
    r = urllib.request.Request(f"{base}/api/endpoints/{EP}/docker/{path}", data=data, headers=hdrs, method=method)
    with urllib.request.urlopen(r, context=ctx(), timeout=timeout) as resp:
        raw = resp.read(); return json.loads(raw) if raw.strip() else {}

base = ks("portainer-url"); tok = ks("portainer-token")

# Delete old helper
try: api(base, tok, "DELETE", "containers/wazuh-readfile?force=true")
except: pass

# Create container to read the file
cr = api(base, tok, "POST", "containers/create?name=wazuh-readfile", {
    "Image": "wazuh/wazuh-dashboard:4.9.2",
    "User": "root",
    "Entrypoint": ["/bin/sh"],
    "Cmd": ["-c", "echo '=== Removing wazuh/config/wazuh.yml ==='; rm -f /target/wazuh/config/wazuh.yml; echo 'Done. Contents:'; ls -la /target/wazuh/config/ 2>&1"],
    "HostConfig": {"Binds": ["/volume1/docker/wazuh/wazuh-dashboard:/target"], "AutoRemove": False}
})
cid = cr.get("Id","")
print(f"Container: {cid[:12]}")
api(base, tok, "POST", f"containers/{cid}/start", body={}, timeout=10)
time.sleep(5)
r = urllib.request.Request(f"{base}/api/endpoints/{EP}/docker/containers/{cid}/logs?stdout=1&stderr=1&tail=50", headers={"X-API-Key": tok})
with urllib.request.urlopen(r, context=ctx(), timeout=15) as resp:
    raw = resp.read()
import struct
i = 0
while i + 8 <= len(raw):
    sz = struct.unpack('>I', raw[i+4:i+8])[0]; i += 8
    if i + sz <= len(raw): print(raw[i:i+sz].decode('utf-8','replace'), end='')
    i += sz
try: api(base, tok, "DELETE", f"containers/{cid}?force=true")
except: pass
