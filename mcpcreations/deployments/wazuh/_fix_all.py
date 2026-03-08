#!/usr/bin/env python3
"""
Comprehensive fix for all 3 wazuh container issues:
1. Create symlinks in certs dir (indexer.pem -> wazuh.indexer.pem etc.)
2. Pre-populate /volume1/docker/wazuh/wazuh-manager from the image's /var/ossec
3. Fix dashboard data dir ownership
"""
import json, subprocess, ssl, sys, time, urllib.request, urllib.error

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
def post(base, tok, path, body, timeout=60):
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
def run_container(base, tok, ep, image, name, cmd, user="root", binds=None, wait_s=10):
    docker_del(base, tok, ep, f"containers/{name}?force=true")
    body = {
        "Image": image,
        "Entrypoint": ["/bin/sh", "-c"],
        "Cmd": [cmd],
        "User": user,
        "HostConfig": {"Binds": binds or [], "AutoRemove": False},
    }
    r = post(base, tok, f"endpoints/{ep}/docker/containers/create?name={name}", body)
    cid = r["Id"]
    req = urllib.request.Request(
        f"{base}/api/endpoints/{ep}/docker/containers/{cid}/start",
        data=b"{}", headers={"X-API-Key": tok, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, context=ssl_ctx(), timeout=15) as resp: resp.read()

    deadline = time.time() + 300  # max 5 min
    while time.time() < deadline:
        inspect = get(base, tok, f"endpoints/{ep}/docker/containers/{cid}/json")
        state = inspect.get("State", {})
        if not state.get("Running", True):
            ec = state.get("ExitCode", -1)
            break
        elapsed = time.time() - (deadline - 300)
        print(f"  running... ({int(elapsed)}s)", end="\r")
        time.sleep(3)
    else:
        ec = -1
        print("\n  TIMEOUT")

    lr = urllib.request.Request(
        f"{base}/api/endpoints/{ep}/docker/containers/{cid}/logs?stdout=true&stderr=true&tail=60",
        headers={"X-API-Key": tok})
    with urllib.request.urlopen(lr, context=ssl_ctx(), timeout=10) as resp:
        logs = resp.read().decode(errors="replace")
    docker_del(base, tok, ep, f"containers/{cid}?force=true")
    return ec, logs

base = ks("portainer-url"); tok = ks("portainer-token"); EP = 2

# ── Step 1: Stop all wazuh containers first ──────────────────────────────────
print("[0/3] Stopping running wazuh containers...")
cs = get(base, tok, f"endpoints/{EP}/docker/containers/json?all=true")
for c in cs:
    names = ','.join(c.get('Names', []))
    if 'wazuh' not in names: continue
    if c.get('State') in ('running', 'restarting'):
        print(f"  Stopping {names}...")
        try:
            req = urllib.request.Request(
                f"{base}/api/endpoints/{EP}/docker/containers/{c['Id']}/stop?t=5",
                data=b"{}", headers={"X-API-Key": tok, "Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, context=ssl_ctx(), timeout=15) as resp: resp.read()
        except urllib.error.HTTPError as e:
            if e.code not in (304, 409): print(f"  Stop error: {e.code}")

# ── Step 2: Create certs symlinks + fix permissions ──────────────────────────
print("\n[1/3] Creating cert symlinks and fixing permissions...")
symlink_cmd = (
    "echo '=== Creating symlinks ===' && "
    "cd /certs && "
    # Short names (indexer expects these from default opensearch.yml)
    "ln -sf wazuh.indexer.pem indexer.pem && "
    "ln -sf wazuh.indexer-key.pem indexer-key.pem && "
    # Admin (same)
    "ln -sf admin.pem admin.pem.link 2>/dev/null || true && "
    # Dashboard short names (in case dashboard image expects these)
    "ln -sf wazuh.dashboard.pem dashboard.pem && "
    "ln -sf wazuh.dashboard-key.pem dashboard-key.pem && "
    # Manager short names
    "ln -sf wazuh.manager.pem server.pem && "
    "ln -sf wazuh.manager-key.pem server-key.pem && "
    # Ensure dir and files are readable
    "chmod 755 /certs && "
    "chmod 644 /certs/*.pem /certs/*.key 2>/dev/null && "
    "echo '=== Certs dir ===' && ls -la /certs/"
)
ec, logs = run_container(base, tok, EP,
    "wazuh/wazuh-indexer:4.9.2", "wazuh-fix-certs",
    symlink_cmd, user="root",
    binds=["/volume1/docker/wazuh/certs:/certs"])
print(f"  Exit code: {ec}")
print(''.join(ch for l in logs.splitlines() for ch in (l+'\n') if ch>=' ' or ch=='\n'))

# ── Step 3: Pre-populate wazuh-manager data dir from image ──────────────────
print("\n[2/3] Pre-populating wazuh-manager host dir from image /var/ossec...")
prepop_cmd = (
    "echo '=== Copying /var/ossec to /target ===' && "
    "cp -a /var/ossec/. /target/ && "
    "echo '=== Done. Contents ===' && "
    "ls /target/"
)
ec, logs = run_container(base, tok, EP,
    "wazuh/wazuh-manager:4.9.2", "wazuh-prepop-mgr",
    prepop_cmd, user="root",
    binds=["/volume1/docker/wazuh/wazuh-manager:/target"])
print(f"  Exit code: {ec}")
print(''.join(ch for l in logs.splitlines() for ch in (l+'\n') if ch>=' ' or ch=='\n'))

# ── Step 4: Fix dashboard data dir ownership ─────────────────────────────────
print("\n[3/3] Fixing dashboard data dir ownership to 1000:1000...")
dash_cmd = (
    "chown -R 1000:1000 /dash && "
    "chmod 755 /dash && "
    "ls -la /dash/"
)
ec, logs = run_container(base, tok, EP,
    "wazuh/wazuh-indexer:4.9.2", "wazuh-fix-dash",
    dash_cmd, user="root",
    binds=["/volume1/docker/wazuh/wazuh-dashboard:/dash"])
print(f"  Exit code: {ec}")
print(''.join(ch for l in logs.splitlines() for ch in (l+'\n') if ch>=' ' or ch=='\n'))

print("\nDone. Update docker-compose.yml and redeploy stack next.")
