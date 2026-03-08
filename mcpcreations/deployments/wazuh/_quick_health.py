#!/usr/bin/env python3
"""Quick check: container health statuses."""
import json, subprocess, ssl, urllib.request

def ks(a):
    return subprocess.run(["security","find-generic-password","-s","portainer-mcp","-a",a,"-w"],
        capture_output=True, text=True).stdout.strip()

def ssl_ctx():
    c = ssl.create_default_context(); c.check_hostname = False; c.verify_mode = ssl.CERT_NONE; return c

def docker(base, tok, ep, method, path, body=None):
    url = f"{base}/api/endpoints/{ep}/docker/{path}"
    data = json.dumps(body).encode() if body else None
    headers = {"X-API-Key": tok}
    if data: headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    with urllib.request.urlopen(r, context=ssl_ctx(), timeout=30) as resp:
        return json.loads(resp.read())

base = ks("portainer-url"); tok = ks("portainer-token")
containers = docker(base, tok, 2, "GET", "containers/json?all=1")
print("Container health:")
for c in sorted(containers, key=lambda x: x["Names"][0]):
    name = c["Names"][0].lstrip("/")
    if "wazuh" in name:
        print(f"  {name:30s}  {c['Status']}")
