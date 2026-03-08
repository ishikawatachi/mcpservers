#!/usr/bin/env python3
"""
_fix_dashboard_config.py

Writes a custom opensearch_dashboards.yml to Synology so the dashboard:
  - Listens on port 5601 plain HTTP (NPM handles external TLS)
  - Connects to OpenSearch backend over HTTPS
  - Pre-creates the wazuh/config/ dir so wazuh_app_config.sh can write wazuh.yml

Files written to /volume1/docker/wazuh/wazuh-dashboard/ (existing dir):
  opensearch_dashboards.yml  → mounted at /usr/share/wazuh-dashboard/config/opensearch_dashboards.yml
  wazuh/config/              → pre-created so /wazuh_app_config.sh can write wazuh.yml
"""
import base64, json, ssl, subprocess, sys, time, urllib.request, urllib.error

EP = 2

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

# Pre-populate wazuh.yml so wazuhCore plugin doesn't crash
# This is exactly what wazuh_app_config.sh would write
WAZUH_YML = """\
hosts:
  - default:
      url: https://wazuh.manager
      port: 55000
      username: wazuh-wui
      password: "zvpvy.w5U2B3Ej6rPnCVCT.G3I1no.KN"
      run_as: false
"""

def ks(a):
    return subprocess.run(
        ["security", "find-generic-password", "-s", "portainer-mcp", "-a", a, "-w"],
        capture_output=True, text=True).stdout.strip()

def ctx():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c

def docker_req(base, tok, method, path, body=None, timeout=30):
    data = json.dumps(body if body is not None else {}).encode() if method in ("POST", "PUT") else None
    headers = {"X-API-Key": tok}
    if data:
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(
        f"{base}/api/endpoints/{EP}/docker/{path}",
        data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, context=ctx(), timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="replace")
        print(f"  HTTP {e.code}: {err_body[:300]}")
        raise

def run_container(base, tok, image, cmd_args, binds, name, user="root"):
    try:
        docker_req(base, tok, "DELETE", f"containers/{name}?force=true")
    except Exception:
        pass

    print(f"  Creating container {name} ...")
    cid_resp = docker_req(base, tok, "POST",
        f"containers/create?name={name}",
        {
            "Image": image,
            "User": user,
            "Entrypoint": ["/bin/sh"],
            "Cmd": ["-c", cmd_args],
            "HostConfig": {
                "Binds": binds,
                "AutoRemove": False,
            }
        })
    cid = cid_resp.get("Id", "")
    if not cid:
        print(f"  ERROR: {cid_resp}")
        sys.exit(1)
    print(f"  Container ID: {cid[:12]}")

    docker_req(base, tok, "POST", f"containers/{cid}/start", timeout=10)
    print("  Container started, waiting...")

    for i in range(30):
        time.sleep(2)
        info = docker_req(base, tok, "GET", f"containers/{cid}/json")
        state = info.get("State", {})
        if state.get("Status") == "exited":
            exit_code = state.get("ExitCode", -1)
            print(f"  Exited: {exit_code}")
            break
        print(f"    [{i*2+2}s] {state.get('Status')}...")

    r = urllib.request.Request(
        f"{base}/api/endpoints/{EP}/docker/containers/{cid}/logs?stdout=1&stderr=1&tail=30",
        headers={"X-API-Key": tok})
    with urllib.request.urlopen(r, context=ctx(), timeout=15) as resp:
        raw_logs = resp.read()
    lines = []
    for line in raw_logs.split(b"\n"):
        if len(line) > 8:
            line = line[8:]
        lines.append(line.decode("utf-8", errors="replace"))
    print("\n--- logs ---")
    print("\n".join(lines[-20:]))
    print("--- end ---")

    try:
        docker_req(base, tok, "DELETE", f"containers/{cid}?force=true")
    except Exception:
        pass

    return exit_code if 'exit_code' in dir() else -1


def main():
    base = ks("portainer-url")
    tok  = ks("portainer-token")
    if not base or not tok:
        print("ERROR: portainer credentials not in keychain")
        sys.exit(1)
    print(f"Portainer: {base}")

    b64 = base64.b64encode(DASHBOARD_YML.encode()).decode()
    b64_wazuh = base64.b64encode(WAZUH_YML.encode()).decode()

    cmd = (
        # Pre-create wazuh/config dir and write wazuh.yml
        "mkdir -p /target/wazuh/config && "
        f"echo '{b64_wazuh}' | base64 -d > /target/wazuh/config/wazuh.yml && "
        # Set ownership to UID=1000 (dashboard user) on the whole data directory
        "chown -R 1000:1000 /target/wazuh && "
        "chmod -R 755 /target/wazuh && "
        # Write opensearch_dashboards.yml (also owned by 1000)
        f"echo '{b64}' | base64 -d > /target/opensearch_dashboards.yml && "
        "chown 1000:1000 /target/opensearch_dashboards.yml && "
        "echo 'DONE' && "
        "cat /target/opensearch_dashboards.yml"
    )

    print("\n=== Writing dashboard config files to Synology ===")
    exit_code = run_container(base, tok,
        "wazuh/wazuh-indexer:4.9.2",  # has sh + base64; runs as root when user=root
        cmd,
        ["/volume1/docker/wazuh/wazuh-dashboard:/target"],
        "wazuh-dash-config-writer",
        user="root")

    if exit_code != 0:
        print(f"\nERROR: exit {exit_code}")
        sys.exit(1)

    print("\n✓ Files written to /volume1/docker/wazuh/wazuh-dashboard/")
    print("\nAdd to docker-compose.yml dashboard volumes:")
    print("  - /volume1/docker/wazuh/wazuh-dashboard/opensearch_dashboards.yml:/usr/share/wazuh-dashboard/config/opensearch_dashboards.yml")


if __name__ == "__main__":
    main()
