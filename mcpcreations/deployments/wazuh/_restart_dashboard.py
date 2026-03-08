#!/usr/bin/env python3
"""Restart the wazuh-dashboard container."""
import json, ssl, subprocess, urllib.request

EP = 2

def ks(a): return subprocess.run(["security","find-generic-password","-s","portainer-mcp","-a",a,"-w"], capture_output=True, text=True).stdout.strip()
def ctx():
    c = ssl.create_default_context(); c.check_hostname = False; c.verify_mode = ssl.CERT_NONE; return c
def api(base, tok, method, path, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    if data is None and method in ("POST","PUT"): data = b""
    hdrs = {"X-API-Key": tok}
    if data: hdrs["Content-Type"] = "application/json"
    r = urllib.request.Request(f"{base}/api/endpoints/{EP}/docker/{path}", data=data, headers=hdrs, method=method)
    with urllib.request.urlopen(r, context=ctx(), timeout=timeout) as resp:
        raw = resp.read(); return json.loads(raw) if raw.strip() else {}

base = ks("portainer-url"); tok = ks("portainer-token")
cs = api(base, tok, "GET", "containers/json?all=true")
dash = next((c for c in cs if "wazuh-dashboard" in ",".join(c.get("Names",[]))), None)
if not dash:
    print("wazuh-dashboard not found"); exit(1)
print(f"Dashboard: {dash['Id'][:12]}  state={dash['State']}  {dash['Status']}")

if dash['State'] in ('running',):
    endpoint = "restart"
else:
    endpoint = "start"

r = urllib.request.Request(
    f"{base}/api/endpoints/{EP}/docker/containers/{dash['Id']}/{endpoint}",
    data=b"{}", headers={"X-API-Key": tok, "Content-Type": "application/json"}, method="POST")
try:
    with urllib.request.urlopen(r, context=ctx(), timeout=120) as resp:
        print(f"{endpoint.title()}: HTTP {resp.status}")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"HTTP {e.code}: {e.reason}  body={body[:200]}")
print(f"Done.")
