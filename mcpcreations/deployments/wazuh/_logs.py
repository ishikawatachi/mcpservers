#!/usr/bin/env python3
"""Get last N lines of logs for a specific wazuh container."""
import json, subprocess, ssl, sys, urllib.request

def ks(a):
    return subprocess.run(
        ["security","find-generic-password","-s","portainer-mcp","-a",a,"-w"],
        capture_output=True, text=True).stdout.strip()
def ssl_ctx():
    c = ssl.create_default_context(); c.check_hostname = False; c.verify_mode = ssl.CERT_NONE; return c
def get(base, tok, path, timeout=20):
    r = urllib.request.Request(f"{base}/api/{path}", headers={"X-API-Key": tok})
    with urllib.request.urlopen(r, context=ssl_ctx(), timeout=timeout) as resp:
        return json.loads(resp.read())

base = ks("portainer-url"); tok = ks("portainer-token"); EP = 2
target = sys.argv[1] if len(sys.argv) > 1 else "indexer"
lines = int(sys.argv[2]) if len(sys.argv) > 2 else 30

cs = get(base, tok, f"endpoints/{EP}/docker/containers/json?all=true")
for c in cs:
    names = ','.join(c.get('Names', []))
    if target.lower() not in names.lower():
        continue
    cid = c['Id']
    print(f"{names}  state={c['State']}  status={c['Status']}")
    r = urllib.request.Request(
        f"{base}/api/endpoints/{EP}/docker/containers/{cid}/logs?"
        f"stdout=true&stderr=true&tail={lines}&timestamps=true",
        headers={"X-API-Key": tok})
    with urllib.request.urlopen(r, context=ssl_ctx(), timeout=20) as lr:
        logs = lr.read().decode(errors="replace")
    for line in logs.splitlines():
        # strip Docker stream framing prefix bytes (first 8 bytes are framing)
        clean = ''.join(ch for ch in line if ch >= ' ' or ch == '\n')
        if clean.strip():
            print(clean)
    break
