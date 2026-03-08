#!/usr/bin/env python3
"""
Fix wazuh-manager crash loop by writing filebeat.yml.
Retries until it catches the container while running (crash cycle ~20s).
"""
import time, json, ssl, struct, subprocess, urllib.request, base64

EP = 2

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

base = ks("portainer-url")
tok = ks("portainer-token")

INDEXER_PASS = "Wazuh!!Wazuh!!"

# Filebeat config content — will be written as a Python file to avoid heredoc issues
FILEBEAT_CONTENT = "\n".join([
    "# Wazuh - Filebeat configuration file",
    "output.opensearch:",
    "  hosts: ['https://wazuh.indexer:9200']",
    "  protocol: https",
    "  username: 'admin'",
    f"  password: '{INDEXER_PASS}'",
    "  ssl.certificate_authorities: ['/etc/ssl/root-ca.pem']",
    "  ssl.certificate: '/etc/ssl/wazuh.manager.pem'",
    "  ssl.key: '/etc/ssl/wazuh.manager-key.pem'",
    "  ssl.verification_mode: none",
    "",
    "filebeat.modules:",
    "  - module: wazuh",
    "    alerts:",
    "      enabled: true",
    "    archives:",
    "      enabled: false",
    "",
    "# Index templates already exist in OpenSearch from previous run",
    "setup.template.json.enabled: false",
    "setup.template.enabled: false",
    "setup.ilm.enabled: false",
])

# Write file using python3 inside the container to avoid heredoc quoting issues
WRITE_PYTHON = ""  # unused now

def get_mgr():
    cs = docker(base, tok, "GET", "containers/json?all=true")
    return next((c for c in cs if "wazuh-manager" in ",".join(c.get("Names",[])) and c["State"] == "running"), None)

# ── Try to catch the manager while running ──────────────────────────────────
print("Waiting to catch wazuh-manager container while running...")
for attempt in range(20):
    mgr = get_mgr()
    if mgr:
        cid = mgr["Id"]
        print(f"Got manager: {cid[:12]} (attempt {attempt+1})")
        break
    print(f"  Attempt {attempt+1}: not running, waiting 3s...")
    time.sleep(3)
else:
    print("FAILED: manager never became running in 60s. Check Docker logs.")
    exit(1)

# ── 1. Check permanent_data.env ───────────────────────────────────────────────
print("\n" + "=" * 60)
print("1. permanent_data.env PERMANENT_DATA array")
print("=" * 60)
out = exec_in(base, tok, cid,
    "grep -A 50 'PERMANENT_DATA' /permanent_data.env 2>&1 | head -30",
    timeout=10)
print(out)

# ── 2. Write filebeat.yml via base64 to avoid shell quoting issues ────────────
print("=" * 60)
print("2. Writing filebeat.yml via base64 in container")
print("=" * 60)
# Encode the content as base64 to safely pass it through the shell
content_b64 = base64.b64encode(FILEBEAT_CONTENT.encode()).decode()
write_cmd = (
    f"mkdir -p /var/ossec/data_tmp/permanent/etc/filebeat /etc/filebeat && "
    f"echo '{content_b64}' | base64 -d > /var/ossec/data_tmp/permanent/etc/filebeat/filebeat.yml && "
    f"cp /var/ossec/data_tmp/permanent/etc/filebeat/filebeat.yml /etc/filebeat/filebeat.yml && "
    f"echo 'Write OK' && ls -la /etc/filebeat/filebeat.yml"
)
mgr = get_mgr()  # Re-fetch in case it restarted
if mgr:
    out = exec_in(base, tok, mgr["Id"], write_cmd, timeout=20)
    print(out)
else:
    print("Manager restarted — retrying write...")
    for _ in range(10):
        time.sleep(3)
        mgr = get_mgr()
        if mgr:
            out = exec_in(base, tok, mgr["Id"], write_cmd, timeout=20)
            print(out)
            break
    else:
        print("FAILED: could not write file")
        exit(1)

# ── 3. Verify written files ───────────────────────────────────────────────────
print("=" * 60)
print("3. Verify /etc/filebeat/filebeat.yml")
print("=" * 60)
time.sleep(2)
mgr = get_mgr()
if mgr:
    out = exec_in(base, tok, mgr["Id"],
        "cat /etc/filebeat/filebeat.yml 2>&1 | head -20; "
        "echo '--- data_tmp ---'; "
        "head -5 /var/ossec/data_tmp/permanent/etc/filebeat/filebeat.yml 2>&1",
        timeout=10)
    print(out)

# ── 4. Wait and check if crash loop stops ────────────────────────────────────
print("=" * 60)
print("4. Waiting 40s to see if crash loop stops...")
print("=" * 60)
time.sleep(40)

cs = docker(base, tok, "GET", "containers/json?all=true")
mgr_detail = next((c for c in cs if "wazuh-manager" in ",".join(c.get("Names",[])) and c["State"] == "running"), None)
if mgr_detail:
    detail = docker(base, tok, "GET", f"containers/{mgr_detail['Id']}/json")
    restarts = detail.get("RestartCount", 0)
    started = detail.get("State", {}).get("StartedAt", "?")
    health = detail.get("State", {}).get("Health", {}).get("Status", "?")
    print(f"Manager: running (id={mgr_detail['Id'][:12]})")
    print(f"  RestartCount: {restarts}")
    print(f"  StartedAt: {started}")
    print(f"  Health: {health}")
    print(f"  Status: {mgr_detail.get('Status')}")
else:
    print("Manager is NOT running after 40s wait — crash loop may still be active")
    cs = docker(base, tok, "GET", "containers/json?all=true")
    mgr_all = next((c for c in cs if "wazuh-manager" in ",".join(c.get("Names",[]))) , None)
    if mgr_all:
        print(f"  Container state: {mgr_all.get('State')} / {mgr_all.get('Status')}")
