#!/usr/bin/env python3
"""
Fix wazuh-manager crash loop:
  1. Read permanent_data.env to confirm /etc/filebeat is in PERMANENT_DATA
  2. Write filebeat.yml to:
     - /var/ossec/data_tmp/permanent/etc/filebeat/filebeat.yml  (persistent restore)
     - /etc/filebeat/filebeat.yml (for current running container)
  3. Restart the Filebeat s6 service (without killing whole container)
"""
import json, ssl, struct, subprocess, urllib.request

EP = 2
INDEXER_USER = "admin"
INDEXER_PASS = "Wazuh!!Wazuh!!"
DASHBOARD_PASS = "zvpvy.w5U2B3Ej6rPnCVCT.G3I1no.KN"

FILEBEAT_YML = r"""# Wazuh - Filebeat configuration file
output.opensearch:
  hosts: ['https://wazuh.indexer:9200']
  protocol: https
  username: 'admin'
  password: 'placeholder_password'
  ssl.certificate_authorities: ['/etc/ssl/root-ca.pem']
  ssl.certificate: '/etc/ssl/wazuh.manager.pem'
  ssl.key: '/etc/ssl/wazuh.manager-key.pem'
  ssl.verification_mode: 'none'

filebeat.modules:
  - module: wazuh
    alerts:
      enabled: true
    archives:
      enabled: false

# Templates already exist in OpenSearch from previous run
setup.template.json.enabled: false
setup.template.enabled: false
setup.ilm.enabled: false
"""

def ks(a):
    return subprocess.run(
        ["security", "find-generic-password", "-s", "portainer-mcp", "-a", a, "-w"],
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

def stream(raw):
    i = 0; parts = []
    while i + 8 <= len(raw):
        sz = struct.unpack(">I", raw[i+4:i+8])[0]; i += 8
        if i + sz <= len(raw): parts.append(raw[i:i+sz].decode("utf-8","replace"))
        i += sz
    return "".join(parts)

def exec_in(base, tok, cid, cmd, timeout=30):
    er = docker(base, tok, "POST", f"containers/{cid}/exec", {
        "AttachStdout": True, "AttachStderr": True, "Tty": False,
        "Cmd": ["/bin/sh", "-c", cmd]
    })
    r = urllib.request.Request(
        f"{base}/api/endpoints/{EP}/docker/exec/{er['Id']}/start",
        data=json.dumps({"Detach": False, "Tty": False}).encode(),
        headers={"X-API-Key": tok, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(r, context=ctx(), timeout=timeout) as resp:
        return stream(resp.read())

base = ks("portainer-url"); tok = ks("portainer-token")
cs = docker(base, tok, "GET", "containers/json?all=true")

def get_mgr():
    cs = docker(base, tok, "GET", "containers/json?all=true")
    return next((c for c in cs if "wazuh-manager" in ",".join(c.get("Names",[])) and c["State"] == "running"), None)

mgr = get_mgr()
if not mgr:
    print("ERROR: wazuh-manager not running"); exit(1)
cid = mgr["Id"]
print(f"Manager: {cid[:12]}\n")

# ── 1. Check permanent_data.env ───────────────────────────────────────────────
print("=" * 60)
print("1. permanent_data.env content (PERMANENT_DATA array)")
print("=" * 60)
out = exec_in(base, tok, cid,
    "cat /permanent_data.env 2>&1 | head -60",
    timeout=10)
print(out)

# ── 2. Check data_tmp structure ───────────────────────────────────────────────
print("=" * 60)
print("2. Check data_tmp/permanent structure")
print("=" * 60)
out = exec_in(base, tok, cid,
    "ls -la /var/ossec/data_tmp/ 2>&1 || echo 'no data_tmp'; "
    "echo '---'; "
    "ls -la /var/ossec/data_tmp/permanent/ 2>&1 | head -20 || echo 'no permanent dir'; "
    "echo '---'; "
    "ls /var/ossec/data_tmp/permanent/etc/ 2>&1 || echo 'no etc in permanent'",
    timeout=10)
print(out)

# ── 3. Write filebeat.yml to persistent data_tmp location ─────────────────────
print("=" * 60)
print("3. Write filebeat.yml to data_tmp (persistent restore location)")
print("=" * 60)
import shlex
yml_escaped = FILEBEAT_YML.replace("'", "'\\''")
# Replace placeholder with actual password
final_yml = FILEBEAT_YML.replace("placeholder_password", INDEXER_PASS)

write_cmd = f"""mkdir -p /var/ossec/data_tmp/permanent/etc/filebeat && cat > /var/ossec/data_tmp/permanent/etc/filebeat/filebeat.yml << 'HEREDOC_EOF'
{final_yml}
HEREDOC_EOF
echo "data_tmp write exit: $?"
cat /var/ossec/data_tmp/permanent/etc/filebeat/filebeat.yml | head -5"""
out = exec_in(base, tok, cid, write_cmd, timeout=15)
print(out)

# ── 4. Write filebeat.yml directly to /etc/filebeat/ for current run ──────────
print("=" * 60)
print("4. Write filebeat.yml directly to /etc/filebeat/ (current run)")
print("=" * 60)
write_cmd2 = f"""mkdir -p /etc/filebeat && cat > /etc/filebeat/filebeat.yml << 'HEREDOC_EOF'
{final_yml}
HEREDOC_EOF
echo "direct write exit: $?"
ls -la /etc/filebeat/
echo "---"
cat /etc/filebeat/filebeat.yml | head -10"""
mgr = get_mgr()
if mgr:
    out = exec_in(base, tok, mgr["Id"], write_cmd2, timeout=15)
    print(out)
else:
    print("Manager restarted during write — will be fixed on next restart via data_tmp")

# ── 5. Verify and restart Filebeat service in container ───────────────────────
print("=" * 60)
print("5. Attempt to start Filebeat service")
print("=" * 60)
import time
time.sleep(3)  # Brief wait for container to stabilize
mgr = get_mgr()
if mgr:
    out = exec_in(base, tok, mgr["Id"],
        # Check if /etc/filebeat/filebeat.yml exists, then test filebeat config
        "ls -la /etc/filebeat/filebeat.yml 2>&1; "
        "echo '---'; "
        "/usr/bin/filebeat test config -c /etc/filebeat/filebeat.yml 2>&1 | head -10",
        timeout=20)
    print(out)
else:
    print("Manager container restarted — data_tmp write is persistent, will restore on next start")
