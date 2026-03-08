#!/usr/bin/env python3
"""Query Portainer via REST API using only stdlib (no venv needed)."""
import json, subprocess, sys, ssl, urllib.request

def _keychain(account):
    r = subprocess.run(["security","find-generic-password","-s","portainer-mcp","-a",account,"-w"], capture_output=True, text=True)
    return r.stdout.strip()

def api(base, tok, path):
    req = urllib.request.Request(f"{base}/api/{path}", headers={"X-API-Key": tok})
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
        return json.loads(r.read())

def main():
    base = _keychain("portainer-url")
    tok  = _keychain("portainer-token")
    print(f"Portainer: {base}\n")
    eps = api(base, tok, "endpoints")
    print("=== ENDPOINTS ===")
    for e in eps:
        print(f"  id={e['Id']}  name={e['Name']}  status={e.get('Status')}")
    stacks = api(base, tok, "stacks")
    print(f"\n=== STACKS ({len(stacks)}) ===")
    for s in stacks:
        print(f"  id={s.get('Id')}  name={s.get('Name')}  ep={s.get('EndpointId')}  status={s.get('Status')}")
    ep_id = 2
    containers = api(base, tok, f"endpoints/{ep_id}/docker/containers/json?all=true")
    print(f"\n=== CONTAINERS ep={ep_id} ({len(containers)} total) ===")
    for c in containers:
        names = ','.join(c.get('Names', []))
        print(f"  {c.get('State','?'):10s}  {names:40s}  {c.get('Image','')[:60]}")
    networks = api(base, tok, f"endpoints/{ep_id}/docker/networks")
    print(f"\n=== NETWORKS ep={ep_id} ===")
    for n in sorted(networks, key=lambda x: x.get('Name','')):
        print(f"  {n.get('Name',''):30s}  driver={n.get('Driver',''):10s}  internal={n.get('Internal',False)}")

main()
