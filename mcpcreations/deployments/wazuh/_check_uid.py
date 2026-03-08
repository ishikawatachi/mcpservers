#!/usr/bin/env python3
"""Check dashboard container UID and current wazuh container states."""
import json, subprocess, ssl, urllib.request, time

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
def post(base, tok, path, body, timeout=30):
    data = json.dumps(body).encode()
    r = urllib.request.Request(f"{base}/api/{path}", data=data,
        headers={"X-API-Key": tok, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(r, context=ssl_ctx(), timeout=timeout) as resp:
        raw = resp.read(); return json.loads(raw) if raw.strip() else {}
def docker_del(base, tok, ep, path):
    r = urllib.request.Request(f"{base}/api/endpoints/{ep}/docker/{path}",
        headers={"X-API-Key": tok}, method="DELETE")
    try:
        with urllib.request.urlopen(r, context=ssl_ctx(), timeout=10) as resp: resp.read()
    except urllib.error.HTTPError as e:
        if e.code not in (404, 409): raise

base = ks("portainer-url"); tok = ks("portainer-token"); EP = 2

# Check dashboard image user UID
print("=== Checking wazuh-dashboard UID ===")
body = {
    "Image": "wazuh/wazuh-dashboard:4.9.2",
    "Entrypoint": ["/bin/sh", "-c"],
    "Cmd": ["id && ls -la /usr/share/wazuh-dashboard/data 2>/dev/null | head -5 || echo 'data dir not found (expected)'"],
    "User": "",  # use the default image user
    "HostConfig": {"AutoRemove": False},
}
docker_del(base, tok, EP, "containers/wazuh-uid-check?force=true")
try:
    r = post(base, tok, f"endpoints/{EP}/docker/containers/create?name=wazuh-uid-check", body)
    cid = r["Id"]
    start_req = urllib.request.Request(
        f"{base}/api/endpoints/{EP}/docker/containers/{cid}/start",
        data=b"{}", headers={"X-API-Key": tok, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(start_req, context=ssl_ctx(), timeout=10) as resp: resp.read()
    time.sleep(5)
    log_req = urllib.request.Request(
        f"{base}/api/endpoints/{EP}/docker/containers/{cid}/logs?stdout=true&stderr=true&tail=10",
        headers={"X-API-Key": tok})
    with urllib.request.urlopen(log_req, context=ssl_ctx(), timeout=10) as lr:
        logs = lr.read().decode(errors="replace")
    print(''.join(ch for line in logs.splitlines() for ch in (line + '\n') if ch >= ' ' or ch == '\n'))
    docker_del(base, tok, EP, f"containers/{cid}?force=true")
except Exception as e:
    print(f"UID check failed: {e}")

# Current container states
print("\n=== Wazuh container states ===")
cs = get(base, tok, f"endpoints/{EP}/docker/containers/json?all=true")
for c in cs:
    name = ','.join(c.get('Names', []))
    if 'wazuh' not in name: continue
    print(f"  {c.get('State','?'):12s}  {c.get('Status',''):40s}  {name}")
