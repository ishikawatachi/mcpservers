#!/usr/bin/env python3
"""
One-shot: cleanup orphans -> generate certs -> create wazuh stack.
Images are already on the Synology from the previous attempt.
Certgen uses Docker container API (no YAML parsing / no heredoc issues).
"""
import json, ssl, subprocess, sys, time, urllib.request, urllib.error

INDEXER_PASSWORD  = "Wazuh!!Wazuh!!"
DASHBOARD_PASSWORD = "zvpvy.w5U2B3Ej6rPnCVCT.G3I1no.KN"
HOSTNAME          = "wazuh.local.defaultvaluation.com"
EP                = 2
STACK_NAME        = "wazuh"

COMPOSE = open("docker-compose.yml").read()

# ── helpers ──────────────────────────────────────────────────────────────────
def ks(a):
    return subprocess.run(
        ["security","find-generic-password","-s","portainer-mcp","-a",a,"-w"],
        capture_output=True, text=True).stdout.strip()

def ctx():
    c = ssl.create_default_context()
    c.check_hostname = False; c.verify_mode = ssl.CERT_NONE; return c

def GET(base, tok, path):
    r = urllib.request.Request(f"{base}/api/{path}", headers={"X-API-Key": tok})
    with urllib.request.urlopen(r, context=ctx(), timeout=20) as resp:
        return json.loads(resp.read())

def POST(base, tok, path, body, timeout=30):
    data = json.dumps(body).encode()
    r = urllib.request.Request(f"{base}/api/{path}", data=data,
        headers={"X-API-Key": tok, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(r, context=ctx(), timeout=timeout) as resp:
        raw = resp.read()
        return json.loads(raw) if raw.strip() else {}

def DELETE(base, tok, path):
    r = urllib.request.Request(f"{base}/api/{path}",
        headers={"X-API-Key": tok}, method="DELETE")
    with urllib.request.urlopen(r, context=ctx(), timeout=15) as resp:
        resp.read()

def docker_post(base, tok, path, body, timeout=30):
    data = json.dumps(body).encode()
    r = urllib.request.Request(f"{base}/api/endpoints/{EP}/docker/{path}", data=data,
        headers={"X-API-Key": tok, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(r, context=ctx(), timeout=timeout) as resp:
        raw = resp.read()
        return json.loads(raw) if raw.strip() else {}

def docker_delete(base, tok, path):
    r = urllib.request.Request(f"{base}/api/endpoints/{EP}/docker/{path}",
        headers={"X-API-Key": tok}, method="DELETE")
    try:
        with urllib.request.urlopen(r, context=ctx(), timeout=15) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        if e.code not in (404, 409):
            raise

# ── step 1: clean up orphaned wazuh containers & network ─────────────────────
def cleanup(base, tok):
    print("[1/4] Cleaning up orphaned wazuh containers and network...")
    containers = GET(base, tok, f"endpoints/{EP}/docker/containers/json?all=true")
    for c in containers:
        name = ','.join(c.get('Names', []))
        if 'wazuh' not in name:
            continue
        cid = c['Id'][:12]
        state = c.get('State','')
        print(f"  Removing {name} ({state})...")
        if state == 'running':
            docker_post(base, tok, f"containers/{c['Id']}/stop", {})
        docker_delete(base, tok, f"containers/{c['Id']}?force=true")

    # Remove network
    networks = GET(base, tok, f"endpoints/{EP}/docker/networks")
    for n in networks:
        if 'wazuh' in n.get('Name',''):
            print(f"  Removing network {n['Name']}...")
            docker_delete(base, tok, f"networks/{n['Id']}")
    print("  Done.")

# ── step 2: generate certs via docker container API ───────────────────────────
# Wazuh certgen uses bash grep/awk to parse YAML -- must use scalar ip format
# (not list format) so grep 'ip:' returns the IP on the same line.
CERTS_YML = (
    "nodes:\\n"
    "  indexer:\\n"
    "    - name: wazuh.indexer\\n"
    "      ip: 127.0.0.1\\n"
    "  server:\\n"
    "    - name: wazuh.manager\\n"
    "      ip: 127.0.0.1\\n"
    "  dashboard:\\n"
    "    - name: wazuh.dashboard\\n"
    "      ip: 127.0.0.1\\n"
)

def run_certgen(base, tok):
    print("[2/4] Running cert generator via Docker container API...")
    # Build bash command using $'...' ANSI-C quoting (handles \n as real newlines)
    bash_cmd = (
        "mkdir -p /config && "
        f"printf '%b' '{CERTS_YML}' > /config/certs.yml && "
        "echo '=== certs.yml ===' && cat /config/certs.yml && "
        "/entrypoint.sh"
    )
    body = {
        "Image": "wazuh/wazuh-certs-generator:0.0.2",
        "Entrypoint": ["/bin/bash", "-c"],
        "Cmd": [bash_cmd],
        "HostConfig": {
            "Binds": ["/volume1/docker/wazuh/certs:/certificates"],
        },
    }
    # Remove old certgen container if it exists
    try:
        docker_delete(base, tok, "containers/wazuh-certgen?force=true")
    except Exception:
        pass

    r = docker_post(base, tok, "containers/create?name=wazuh-certgen", body)
    cid = r["Id"]
    print(f"  Container created: {cid[:12]}")

    # Start
    docker_post(base, tok, f"containers/{cid}/start", {})
    print("  Container started, waiting for exit...")

    # Poll for exit
    deadline = time.time() + 120
    while time.time() < deadline:
        inspect = GET(base, tok, f"endpoints/{EP}/docker/containers/{cid}/json")
        state = inspect.get("State", {})
        status = state.get("Status", "")
        running = state.get("Running", True)
        print(f"    status={status}", end="\r")
        if not running:
            exit_code = state.get("ExitCode", -1)
            print(f"\n  Container exited with code {exit_code}")
            if exit_code != 0:
                # Grab logs
                try:
                    log_req = urllib.request.Request(
                        f"{base}/api/endpoints/{EP}/docker/containers/{cid}/logs?stdout=true&stderr=true&tail=40",
                        headers={"X-API-Key": tok})
                    with urllib.request.urlopen(log_req, context=ctx(), timeout=10) as lr:
                        logs = lr.read().decode(errors="replace")
                    print("  === Certgen logs (last 40 lines) ===")
                    print(logs)
                except Exception as le:
                    print(f"  (could not fetch logs: {le})")
                sys.exit("Certgen failed. See logs above.")
            break
        time.sleep(3)
    else:
        sys.exit("Certgen timed out after 120s")

    # Cleanup container
    docker_delete(base, tok, f"containers/{cid}?force=true")
    print("  Certs generated, container removed.")

# ── step 3: create wazuh stack ────────────────────────────────────────────────
def create_stack(base, tok):
    print(f"[3/4] Creating Portainer stack '{STACK_NAME}'...")
    env = [
        {"name": "WAZUH_HOSTNAME",     "value": HOSTNAME},
        {"name": "INDEXER_PASSWORD",   "value": INDEXER_PASSWORD},
        {"name": "DASHBOARD_PASSWORD", "value": DASHBOARD_PASSWORD},
    ]
    body = {
        "name": STACK_NAME,
        "stackFileContent": COMPOSE,
        "env": env,
    }
    try:
        r = POST(base, tok,
                 f"stacks/create/standalone/string?endpointId={EP}",
                 body, timeout=None)
        stack_id = r.get("Id", "?")
        print(f"  Stack created — id={stack_id}")
        return True
    except urllib.error.HTTPError as e:
        if e.code == 504:
            print(f"  Got 504 (images downloading / NPM proxy timeout) — "
                  f"checking if stack was created...")
            time.sleep(10)
            stacks = GET(base, tok, "stacks")
            match = next((s for s in stacks if s["Name"] == STACK_NAME), None)
            if match:
                print(f"  Stack exists in Portainer (id={match['Id']}) — 504 was cosmetic.")
                return True
            print("  Stack not found after 504. Portainer may still be creating it.")
            print("  Check Portainer UI in a minute and look for stack 'wazuh'.")
            return False
        else:
            body_text = e.read().decode(errors="replace")
            sys.exit(f"Stack creation failed: HTTP {e.code} — {body_text[:400]}")

# ── main ──────────────────────────────────────────────────────────────────────
def main():
    base = ks("portainer-url")
    tok  = ks("portainer-token")
    print(f"Portainer: {base}\nEndpoint : {EP}\n")

    cleanup(base, tok)
    run_certgen(base, tok)
    ok = create_stack(base, tok)

    print()
    if ok:
        print("[4/4] Deployment complete!")
        print()
        print(f"  Dashboard : https://{HOSTNAME}")
        print( "  Login     : admin / zvpvy.w5U2B3Ej6rPnCVCT.G3I1no.KN")
        print()
        print("NPM Reverse Proxy:")
        print(f"  Domain   : {HOSTNAME}")
        print( "  Scheme   : http  |  Forward: wazuh-dashboard:5601")
        print()
        print("First startup takes 3-6 min for OpenSearch to initialise.")
    else:
        print("[4/4] Check Portainer UI for stack status.")

main()
