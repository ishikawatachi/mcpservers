#!/usr/bin/env python3
"""Fetch logs for all wazuh containers and also list cert files."""
import json, subprocess, ssl, urllib.request

def ks(a):
    return subprocess.run(
        ["security","find-generic-password","-s","portainer-mcp","-a",a,"-w"],
        capture_output=True, text=True).stdout.strip()

def ssl_ctx():
    c = ssl.create_default_context()
    c.check_hostname = False; c.verify_mode = ssl.CERT_NONE; return c

def get(base, tok, path, timeout=20):
    r = urllib.request.Request(f"{base}/api/{path}", headers={"X-API-Key": tok})
    with urllib.request.urlopen(r, context=ssl_ctx(), timeout=timeout) as resp:
        return json.loads(resp.read())

def get_raw(base, tok, path, timeout=20):
    r = urllib.request.Request(f"{base}/api/{path}", headers={"X-API-Key": tok})
    with urllib.request.urlopen(r, context=ssl_ctx(), timeout=timeout) as resp:
        return resp.read().decode(errors="replace")

def docker_exec(base, tok, ep, cid, cmd):
    """Run a command in a container and return stdout."""
    import urllib.error
    data = json.dumps({"AttachStdout": True, "AttachStderr": True, "Cmd": cmd}).encode()
    req = urllib.request.Request(
        f"{base}/api/endpoints/{ep}/docker/containers/{cid}/exec",
        data=data,
        headers={"X-API-Key": tok, "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, context=ssl_ctx(), timeout=10) as r:
            exec_id = json.loads(r.read())["Id"]
        data2 = json.dumps({"Detach": False, "Tty": True}).encode()
        req2 = urllib.request.Request(
            f"{base}/api/endpoints/{ep}/docker/exec/{exec_id}/start",
            data=data2,
            headers={"X-API-Key": tok, "Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req2, context=ssl_ctx(), timeout=15) as r2:
            return r2.read().decode(errors="replace")
    except Exception as e:
        return f"exec error: {e}"

base = ks("portainer-url")
tok  = ks("portainer-token")
EP   = 2

# --- containers ---
cs = get(base, tok, f"endpoints/{EP}/docker/containers/json?all=true")
wazuh = {}
for c in cs:
    names = ','.join(c.get('Names', []))
    if 'wazuh' in names:
        wazuh[names] = {"id": c["Id"], "state": c.get("State"), "status": c.get("Status")}

print(f"Found {len(wazuh)} wazuh containers:")
for n, v in sorted(wazuh.items()):
    print(f"  {v['state']:10s} {v['status']:40s} {n}")

# --- logs ---
for name, v in sorted(wazuh.items()):
    cid = v["id"]
    print(f"\n{'='*70}")
    print(f"LOGS: {name}  ({v['state']} / {v['status']})")
    print(f"{'='*70}")
    logs = get_raw(base, tok,
                   f"endpoints/{EP}/docker/containers/{cid}/logs?"
                   f"stdout=true&stderr=true&tail=80&timestamps=true")
    # strip Docker log multiplexing header bytes (non-printable)
    lines = []
    for line in logs.splitlines():
        clean = ''.join(ch for ch in line if ch >= ' ' or ch == '\n')
        lines.append(clean)
    print('\n'.join(lines[-80:]))

# --- cert files via indexer exec ---
indexer_id = next((v["id"] for n, v in wazuh.items() if "indexer" in n), None)
if indexer_id:
    print(f"\n{'='*70}")
    print("CERT FILES in /usr/share/wazuh-indexer/certs (via indexer exec):")
    print(f"{'='*70}")
    out = docker_exec(base, tok, EP, indexer_id, ["ls", "-la", "/usr/share/wazuh-indexer/certs/"])
    print(out)
