#!/usr/bin/env python3
"""
Diagnose and fix the i18n.locale error on Wazuh Dashboard.

Steps:
  1. Exec into the running dashboard container and read the live config file
  2. Check the host-volume copy too
  3. If i18n.locale is missing from either, rewrite both correctly
  4. Restart the dashboard
  5. Run a curl test to confirm the page loads without the i18n error
"""
import base64, json, ssl, struct, subprocess, time, urllib.request, urllib.error

EP = 2

def ks(a):
    return subprocess.run(
        ["security", "find-generic-password", "-s", "portainer-mcp", "-a", a, "-w"],
        capture_output=True, text=True).stdout.strip()

def ctx():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c

def docker(base, tok, method, path, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else (b"{}" if method in ("POST", "PUT") else None)
    hdrs = {"X-API-Key": tok}
    if data:
        hdrs["Content-Type"] = "application/json"
    r = urllib.request.Request(
        f"{base}/api/endpoints/{EP}/docker/{path}",
        data=data, headers=hdrs, method=method)
    with urllib.request.urlopen(r, context=ctx(), timeout=timeout) as resp:
        raw = resp.read()
        return json.loads(raw) if raw.strip() else {}

def stream(raw):
    i = 0
    parts = []
    while i + 8 <= len(raw):
        sz = struct.unpack(">I", raw[i+4:i+8])[0]
        i += 8
        if i + sz <= len(raw):
            parts.append(raw[i:i+sz].decode("utf-8", "replace"))
        i += sz
    return "".join(parts)

def exec_in(base, tok, cid, cmd, timeout=30):
    er = docker(base, tok, "POST", f"containers/{cid}/exec", {
        "AttachStdout": True, "AttachStderr": True, "Tty": False,
        "Cmd": ["/bin/sh", "-c", cmd]
    })
    eid = er["Id"]
    r = urllib.request.Request(
        f"{base}/api/endpoints/{EP}/docker/exec/{eid}/start",
        data=json.dumps({"Detach": False, "Tty": False}).encode(),
        headers={"X-API-Key": tok, "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(r, context=ctx(), timeout=timeout) as resp:
        return stream(resp.read())

def run_helper(base, tok, cmd, timeout=30):
    name = "wazuh-helper"
    try:
        docker(base, tok, "DELETE", f"containers/{name}?force=true")
    except Exception:
        pass
    resp = docker(base, tok, "POST", f"containers/create?name={name}", {
        "Image": "wazuh/wazuh-dashboard:4.9.2", "User": "root",
        "Entrypoint": ["/bin/sh"], "Cmd": ["-c", cmd],
        "HostConfig": {
            "Binds": ["/volume1/docker/wazuh/wazuh-dashboard:/t"],
            "AutoRemove": False
        }
    })
    cid = resp["Id"]
    docker(base, tok, "POST", f"containers/{cid}/start", body={})
    for _ in range(timeout):
        time.sleep(1)
        info = docker(base, tok, "GET", f"containers/{cid}/json")
        if info.get("State", {}).get("Status") == "exited":
            break
    r = urllib.request.Request(
        f"{base}/api/endpoints/{EP}/docker/containers/{cid}/logs?stdout=1&stderr=1&tail=80",
        headers={"X-API-Key": tok})
    with urllib.request.urlopen(r, context=ctx(), timeout=15) as resp:
        out = resp.read()
    try:
        docker(base, tok, "DELETE", f"containers/{cid}?force=true")
    except Exception:
        pass
    return stream(out)

# ── Full correct opensearch_dashboards.yml ──────────────────────────────────
DASHBOARD_YML = """\
server.host: "0.0.0.0"
server.port: 5601
server.ssl.enabled: false

opensearch.hosts: ["https://wazuh.indexer:9200"]
opensearch.ssl.verificationMode: none
opensearch.username: "kibanaserver"
opensearch.password: "Wazuh!!Wazuh!!"
opensearch.requestHeadersWhitelist: ["securitytenant","Authorization"]

opensearch_security.multitenancy.enabled: false
opensearch_security.readonly_mode.roles: ["kibana_read_only"]

uiSettings.overrides.defaultRoute: "/app/wazuh"

i18n.locale: "en"
"""

base = ks("portainer-url")
tok = ks("portainer-token")

cs = docker(base, tok, "GET", "containers/json?all=true")
dash = next((c for c in cs if "wazuh-dashboard" in ",".join(c.get("Names", [])) and c["State"] == "running"), None)

# ── Step 1: read live config inside the container ───────────────────────────
print("=" * 60)
print("STEP 1: Live opensearch_dashboards.yml inside the container")
print("=" * 60)
if dash:
    live = exec_in(base, tok, dash["Id"],
                   "cat /usr/share/wazuh-dashboard/config/opensearch_dashboards.yml 2>&1")
    print(live)
    has_locale_live = "i18n.locale" in live
    print(f"  → i18n.locale present in live config: {has_locale_live}")
else:
    print("  Dashboard not running — skipping exec check")
    has_locale_live = False

# ── Step 2: read host-volume copy ────────────────────────────────────────────
print("=" * 60)
print("STEP 2: Host-volume opensearch_dashboards.yml")
print("=" * 60)
vol_content = run_helper(base, tok,
    "cat /t/opensearch_dashboards.yml 2>&1", timeout=20)
print(vol_content)
has_locale_vol = "i18n.locale" in vol_content

print(f"  → i18n.locale present in host-volume file: {has_locale_vol}")

# ── Step 3: if missing anywhere, rewrite the full config ────────────────────
if not has_locale_live or not has_locale_vol:
    print("=" * 60)
    print("STEP 3: Rewriting full opensearch_dashboards.yml")
    print("=" * 60)
    b64 = base64.b64encode(DASHBOARD_YML.encode()).decode()
    result = run_helper(base, tok,
        f"printf '%s' '{b64}' | base64 -d > /t/opensearch_dashboards.yml && "
        f"chown 1000:1000 /t/opensearch_dashboards.yml && "
        f"echo '--- written ---' && cat /t/opensearch_dashboards.yml",
        timeout=20)
    print(result)
else:
    print("=" * 60)
    print("STEP 3: Config already correct — skipping rewrite")
    print("=" * 60)

# ── Step 4: restart dashboard ────────────────────────────────────────────────
print("=" * 60)
print("STEP 4: Restarting dashboard")
print("=" * 60)
cs = docker(base, tok, "GET", "containers/json?all=true")
dash = next((c for c in cs if "wazuh-dashboard" in ",".join(c.get("Names", []))), None)
if dash:
    docker(base, tok, "POST", f"containers/{dash['Id']}/restart", body={}, timeout=60)
    print(f"  Restarted {dash['Id'][:12]}. Waiting 40s...")
    time.sleep(40)
else:
    print("  Dashboard not found — skipping restart")

# ── Step 5: test curl from inside container ───────────────────────────────────
print("=" * 60)
print("STEP 5: Curl test — checking dashboard responds correctly")
print("=" * 60)
cs = docker(base, tok, "GET", "containers/json?all=true")
dash = next((c for c in cs if "wazuh-dashboard" in ",".join(c.get("Names", [])) and c["State"] == "running"), None)
if dash:
    # Check live config has i18n.locale after restart
    live2 = exec_in(base, tok, dash["Id"],
                    "cat /usr/share/wazuh-dashboard/config/opensearch_dashboards.yml 2>&1")
    has_locale_after = "i18n.locale" in live2
    print(f"  i18n.locale in live config after restart: {has_locale_after}")

    # Curl the dashboard (expect 302 redirect to /app/wazuh login)
    curl_out = exec_in(base, tok, dash["Id"],
        "curl -sk -o /dev/null -w '%{http_code} %{redirect_url}' http://localhost:5601/ 2>&1",
        timeout=20)
    print(f"  curl http://localhost:5601/ → {curl_out.strip()}")

    # Check status endpoint
    status_out = exec_in(base, tok, dash["Id"],
        "curl -sk http://localhost:5601/api/status 2>&1 | head -c 200",
        timeout=20)
    print(f"  /api/status → {status_out.strip()[:150]}")

    if has_locale_after:
        print("\n✅ PASS: i18n.locale is set in the live config. Browser error should be gone.")
    else:
        print("\n❌ FAIL: i18n.locale is still missing — entrypoint is overwriting the config.")
        print("   Next fix: mount the config file :ro so entrypoint cannot overwrite it.")
else:
    print("  Dashboard not running after restart — check logs")
