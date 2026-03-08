#!/usr/bin/env python3
"""
_fix_indexer_config.py

Root cause fix for:
  AccessDeniedException: /etc/wazuh-indexer/certs/indexer.pem "read"

The JVM SecurityManager only grants read access within /usr/share/wazuh-indexer/.
The default opensearch.yml points to /etc/wazuh-indexer/certs/ → blocked.

Fix:
  1. Write wazuh.indexer.yml (opensearch config) to
     /volume1/docker/wazuh/indexer-config/opensearch.yml on the Synology
     via a temporary Docker container (Portainer API).
  2. Update docker-compose.yml mounts:
     - certs → /usr/share/wazuh-indexer/certs:ro  (allowed path)
     - config → /volume1/docker/wazuh/indexer-config/opensearch.yml
                → /usr/share/wazuh-indexer/opensearch.yml:ro
"""
import base64, json, ssl, subprocess, sys, time, urllib.request, urllib.error

EP = 2

# ── opensearch.yml content (mirrors official wazuh single-node docker) ────────
OPENSEARCH_YML = """\
network.host: "0.0.0.0"
node.name: "wazuh.indexer"

# single-node mode -- do NOT set cluster.initial_cluster_manager_nodes
cluster.name: "wazuh-cluster"
discovery.type: single-node

path.data: /var/lib/wazuh-indexer
path.logs: /var/log/wazuh-indexer

# bootstrap.memory_lock intentionally omitted: containers lack IPC_LOCK
# and mlockall hangs JVM startup on Synology NAS

plugins.security.ssl.http.pemcert_filepath: /usr/share/wazuh-indexer/certs/wazuh.indexer.pem
plugins.security.ssl.http.pemkey_filepath: /usr/share/wazuh-indexer/certs/wazuh.indexer-key.pem
plugins.security.ssl.http.pemtrustedcas_filepath: /usr/share/wazuh-indexer/certs/root-ca.pem
plugins.security.ssl.transport.pemcert_filepath: /usr/share/wazuh-indexer/certs/wazuh.indexer.pem
plugins.security.ssl.transport.pemkey_filepath: /usr/share/wazuh-indexer/certs/wazuh.indexer-key.pem
plugins.security.ssl.transport.pemtrustedcas_filepath: /usr/share/wazuh-indexer/certs/root-ca.pem
plugins.security.ssl.http.enabled: true
plugins.security.ssl.transport.enabled: true
plugins.security.allow_unsafe_democertificates: false

plugins.security.authcz.admin_dn:
  - "CN=admin,OU=Wazuh,O=Wazuh,L=California,C=US"
plugins.security.check_snapshot_restore_write_privileges: true
plugins.security.enable_snapshot_restore_privilege: true
plugins.security.nodes_dn:
  - "CN=wazuh.indexer,OU=Wazuh,O=Wazuh,L=California,C=US"

plugins.security.restapi.roles_enabled:
  - "all_access"
  - "security_rest_api_access"
plugins.security.system_indices.enabled: true
plugins.security.system_indices.indices:
  - ".plugins-ml-model-group"
  - ".plugins-ml-model"
  - ".plugins-ml-task"
  - ".opendistro-alerting-config"
  - ".opendistro-alerting-alert*"
  - ".opendistro-alerting-alert-comment"
  - ".opendistro-job-scheduler-lock"
  - ".opendistro-reports-*"
  - ".opensearch-notifications-*"
  - ".opensearch-notebooks"
  - ".opensearch-observability"
  - ".ql-datasources"
  - ".opendistro-asynchronous-search-response*"
  - ".replication-metadata-store"
  - ".opensearch-knn-models"
  - ".geospatial-ip2geo-data*"

compatibility.override_main_response_version: true
"""

# ── helpers ───────────────────────────────────────────────────────────────────
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
    # Always send a JSON body for POST (even {} for start) — avoids urllib
    # sending chunked/no-body POST that Docker API rejects.
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

def run_container(base, tok, image, cmd_args, binds, name):
    """Create, start, wait for exit, print logs, delete container."""
    # Remove any existing container with same name
    try:
        docker_req(base, tok, "DELETE", f"containers/{name}?force=true")
        print(f"  Removed existing container {name}")
    except Exception:
        pass

    print(f"  Creating container {name} ...")
    cid_resp = docker_req(base, tok, "POST",
        f"containers/create?name={name}",
        {
            "Image": image,
            "Entrypoint": ["/bin/sh"],
            "Cmd": ["-c"] + [cmd_args],
            "HostConfig": {
                "Binds": binds,
                "AutoRemove": False,
            }
        })
    cid = cid_resp.get("Id", "")
    if not cid:
        print(f"  ERROR creating container: {cid_resp}")
        sys.exit(1)
    print(f"  Container ID: {cid[:12]}")

    docker_req(base, tok, "POST", f"containers/{cid}/start", timeout=10)
    print("  Container started, waiting...")

    for i in range(30):
        time.sleep(2)
        info = docker_req(base, tok, "GET", f"containers/{cid}/json")
        state = info.get("State", {})
        status = state.get("Status", "")
        exit_code = state.get("ExitCode", -1)
        if status == "exited":
            print(f"  Exited with code {exit_code}")
            break
        print(f"    [{i*2+2}s] {status}...")
    else:
        print("  WARNING: container did not exit in 60s")

    # Get logs
    r = urllib.request.Request(
        f"{base}/api/endpoints/{EP}/docker/containers/{cid}/logs?stdout=1&stderr=1&tail=40",
        headers={"X-API-Key": tok})
    with urllib.request.urlopen(r, context=ctx(), timeout=15) as resp:
        raw = resp.read()
    # Docker log stream: each line has 8-byte header → strip non-printable
    lines = []
    for line in raw.split(b"\n"):
        if len(line) > 8:
            line = line[8:]
        try:
            decoded = line.decode("utf-8", errors="replace")
            lines.append(decoded)
        except Exception:
            pass
    print("\n--- logs ---")
    print("\n".join(lines[-30:]))
    print("--- end logs ---")

    # Cleanup
    try:
        docker_req(base, tok, "DELETE", f"containers/{cid}?force=true")
    except Exception:
        pass

    return exit_code


def main():
    base = ks("portainer-url")
    tok  = ks("portainer-token")
    if not base or not tok:
        print("ERROR: portainer credentials not in keychain")
        sys.exit(1)
    print(f"Portainer: {base}")

    # Step 1 — List certs dir to see what's actually there + read DNs
    print("\n=== Step 1: List certs dir and read cert DNs ===")
    dn_cmd = (
        "echo '--- ls /certs ---' && ls -la /certs/ && "
        "echo '' && echo '--- admin cert DN ---' && "
        "(openssl x509 -in /certs/admin.pem -noout -subject 2>/dev/null || echo 'E: admin.pem not readable') && "
        "echo '--- indexer cert DN ---' && "
        "(openssl x509 -in /certs/wazuh.indexer.pem -noout -subject 2>/dev/null || echo 'E: wazuh.indexer.pem not readable')"
    )
    run_container(base, tok,
        "wazuh/wazuh-indexer:4.9.2",
        dn_cmd,
        ["/volume1/docker/wazuh/certs:/certs"],   # no :ro so we can see permissions
        "wazuh-dn-check")

    # Step 2 — write opensearch.yml into the existing wazuh-indexer data dir
    # (avoid creating a new directory; /volume1/docker/wazuh/wazuh-indexer exists)
    print("\n=== Step 2: Write opensearch.yml ===")
    print("  Target: /volume1/docker/wazuh/wazuh-indexer/opensearch.yml")
    b64 = base64.b64encode(OPENSEARCH_YML.encode()).decode()
    write_cmd = (
        f"echo '{b64}' | base64 -d > /target/opensearch.yml && "
        f"echo 'DONE: file written' && "
        f"echo '--- content ---' && "
        f"cat /target/opensearch.yml"
    )
    exit_code = run_container(base, tok,
        "wazuh/wazuh-indexer:4.9.2",
        write_cmd,
        ["/volume1/docker/wazuh/wazuh-indexer:/target"],   # existing dir
        "wazuh-config-writer")

    if exit_code != 0:
        print(f"\nERROR: config writer exited {exit_code}. Aborting.")
        sys.exit(1)

    print("\n✓ opensearch.yml written to /volume1/docker/wazuh/wazuh-indexer/opensearch.yml")
    print("\nNow update docker-compose.yml indexer volumes to:")
    print("  - /volume1/docker/wazuh/certs:/usr/share/wazuh-indexer/certs:ro")
    print("  - /volume1/docker/wazuh/wazuh-indexer:/var/lib/wazuh-indexer          (keep)")
    print("  - /volume1/docker/wazuh/wazuh-indexer/opensearch.yml:/usr/share/wazuh-indexer/opensearch.yml:ro")


if __name__ == "__main__":
    main()
