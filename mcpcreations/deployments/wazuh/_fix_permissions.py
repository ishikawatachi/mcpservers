#!/usr/bin/env python3
"""
Fix permissions on wazuh host volumes.
- certs dir: chmod 755 + 644 for .pem files (readable by all)
- data dirs: chown to wazuh container UIDs
"""
import json, subprocess, ssl, urllib.request, urllib.error, time

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

base = ks("portainer-url")
tok  = ks("portainer-token")
EP   = 2

# First: inspect images to find container UIDs
print("Checking container UIDs from image config...")
for img_name in ["wazuh/wazuh-indexer:4.9.2", "wazuh/wazuh-dashboard:4.9.2", "wazuh/wazuh-manager:4.9.2"]:
    try:
        img = get(base, tok, f"endpoints/{EP}/docker/images/{urllib.request.quote(img_name, safe='')}/json")
        user = img.get("Config", {}).get("User", "(root/empty)")
        print(f"  {img_name.split('/')[1]:30s}  User={user!r}")
    except Exception as e:
        print(f"  Could not inspect {img_name}: {e}")

# Fix: run alpine container as root with all mounts, do chmod/chown
print("\nRunning permission fix container...")

# Remove any leftover
docker_del(base, tok, EP, "containers/wazuh-permfix?force=true")

# The fix commands:
# - certs: chmod 755 dir, 644 all files (readable by any UID)
# - wazuh-indexer data: chown 1000:1000 (standard wazuh-indexer UID)
# - wazuh-dashboard data: chown 1000:1000 (standard wazuh-dashboard UID)
# - wazuh-manager data (/var/ossec): manager runs as root, so just ensure dir exists with 755
fix_cmd = (
    "echo '=== Before ===' && "
    "ls -la /certs/ && "
    "ls -la /idx/ 2>/dev/null | head -3 && "
    "ls -la /dash/ 2>/dev/null | head -3 && "
    "ls -la /mgr/ 2>/dev/null | head -3 && "
    "echo '=== Fixing certs ===' && "
    "chmod 755 /certs && "
    "chmod 644 /certs/*.pem 2>/dev/null || true && "
    "chmod 644 /certs/*.key 2>/dev/null || true && "
    "echo '=== Fixing indexer data dir ===' && "
    "chown -R 1000:1000 /idx && "
    "chmod 755 /idx && "
    "echo '=== Fixing dashboard data dir ===' && "
    "chown -R 1000:1000 /dash && "
    "chmod 755 /dash && "
    "echo '=== Fixing manager data dir ===' && "
    "chmod 755 /mgr && "
    "echo '=== After certs ===' && "
    "ls -la /certs/ && "
    "echo '=== After data dirs ===' && "
    "ls -la /idx/ && "
    "ls -la /dash/ && "
    "echo DONE"
)

body = {
    "Image": "alpine:latest",
    "Entrypoint": ["/bin/sh", "-c"],
    "Cmd": [fix_cmd],
    "User": "root",
    "HostConfig": {
        "Binds": [
            "/volume1/docker/wazuh/certs:/certs",
            "/volume1/docker/wazuh/wazuh-indexer:/idx",
            "/volume1/docker/wazuh/wazuh-dashboard:/dash",
            "/volume1/docker/wazuh/wazuh-manager:/mgr",
        ],
        "AutoRemove": False,
    },
}

# alpine might not be cached -- try with wazuh-indexer image (already on host, runs as root in entrypoint override)
try:
    r = post(base, tok, f"endpoints/{EP}/docker/containers/create?name=wazuh-permfix", body)
    cid = r["Id"]
    print(f"  Container created: {cid[:12]} (using alpine)")
except urllib.error.HTTPError as e:
    err = e.read().decode(errors="replace")
    if "No such image" in err:
        print("  alpine not cached, using wazuh-indexer image instead...")
        body["Image"] = "wazuh/wazuh-indexer:4.9.2"
        r = post(base, tok, f"endpoints/{EP}/docker/containers/create?name=wazuh-permfix", body)
        cid = r["Id"]
        print(f"  Container created: {cid[:12]} (using wazuh-indexer)")
    else:
        raise

# Start
start_req = urllib.request.Request(
    f"{base}/api/endpoints/{EP}/docker/containers/{cid}/start",
    data=b"{}",
    headers={"X-API-Key": tok, "Content-Type": "application/json"},
    method="POST")
with urllib.request.urlopen(start_req, context=ssl_ctx(), timeout=15) as resp:
    resp.read()

# Wait for exit
print("  Waiting for fix to complete...")
deadline = time.time() + 60
while time.time() < deadline:
    inspect = get(base, tok, f"endpoints/{EP}/docker/containers/{cid}/json")
    state = inspect.get("State", {})
    if not state.get("Running", True):
        exit_code = state.get("ExitCode", -1)
        print(f"  Exited with code {exit_code}")
        break
    time.sleep(2)

# Get logs
log_req = urllib.request.Request(
    f"{base}/api/endpoints/{EP}/docker/containers/{cid}/logs?stdout=true&stderr=true&tail=60",
    headers={"X-API-Key": tok})
with urllib.request.urlopen(log_req, context=ssl_ctx(), timeout=10) as lr:
    logs = lr.read().decode(errors="replace")
print("\n=== Fix output ===")
# Clean non-printable Docker log framing bytes
print(''.join(ch for line in logs.splitlines()
              for ch in (line + '\n') if ch >= ' ' or ch == '\n'))

# Cleanup container
docker_del(base, tok, EP, f"containers/{cid}?force=true")
print("\n=== Wazuh containers will recover on next restart ===")
print("Monitor with: python3 _check_logs.py")
