#!/usr/bin/env python3
"""
deploy_wazuh.py
===============
Deploys the Wazuh single-node stack to Portainer via the REST API (stdlib only).

Two-step process
----------------
1. Certgen step  -- deploy docker-compose.certgen.yml, wait for the container to
                    exit successfully, then delete the temporary stack.
                    Skip with --skip-certgen if certs already exist.

2. Main stack    -- deploy docker-compose.yml as stack "wazuh" on endpoint 2.

Credentials are read from macOS Keychain (service "portainer-mcp"):
    security add-generic-password -s portainer-mcp -a portainer-url  -w 'https://...'
    security add-generic-password -s portainer-mcp -a portainer-token -w 'ptr_...'

Usage
-----
    python mcpcreations/deployments/wazuh/deploy_wazuh.py \\
        --indexer-password 'SecurePass1!' \\
        --dashboard-password 'DashPass1!'

    # Skip cert generation (certs already in /volume1/docker/wazuh/certs/)
    python ... --skip-certgen --indexer-password '...' --dashboard-password '...'

    # Dry-run: print what would be sent without calling Portainer
    python ... --dry-run --indexer-password '...' --dashboard-password '...'
"""
from __future__ import annotations

import argparse
import json
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

COMPOSE_FILE         = SCRIPT_DIR / "docker-compose.yml"
CERTGEN_COMPOSE_FILE = SCRIPT_DIR / "docker-compose.certgen.yml"

STACK_NAME         = "wazuh"
CERTGEN_STACK_NAME = "wazuh-certgen"
ENDPOINT_ID        = 2
HOSTNAME           = "wazuh.local.defaultvaluation.com"


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib-only, no venv)
# ---------------------------------------------------------------------------

def _keychain(account: str) -> str:
    r = subprocess.run(
        ["security", "find-generic-password", "-s", "portainer-mcp", "-a", account, "-w"],
        capture_output=True, text=True,
    )
    val = r.stdout.strip()
    if not val:
        sys.exit(f"Keychain entry missing: service=portainer-mcp account={account}")
    return val


def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _api_get(base: str, token: str, path: str) -> object:
    req = urllib.request.Request(
        f"{base}/api/{path}",
        headers={"X-API-Key": token, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, context=_ssl_ctx(), timeout=20) as r:
        return json.loads(r.read())


def _api_post(base: str, token: str, path: str, body: dict,
              timeout: int | None = 30) -> object:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{base}/api/{path}",
        data=data,
        headers={
            "X-API-Key": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, context=_ssl_ctx(), timeout=timeout) as r:
        return json.loads(r.read())


def _api_put(base: str, token: str, path: str, body: dict) -> object:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{base}/api/{path}",
        data=data,
        headers={
            "X-API-Key": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="PUT",
    )
    with urllib.request.urlopen(req, context=_ssl_ctx(), timeout=30) as r:
        return json.loads(r.read())


def _api_delete(base: str, token: str, path: str) -> None:
    req = urllib.request.Request(
        f"{base}/api/{path}",
        headers={"X-API-Key": token},
        method="DELETE",
    )
    with urllib.request.urlopen(req, context=_ssl_ctx(), timeout=15) as r:
        r.read()


# ---------------------------------------------------------------------------
# Portainer stack operations
# ---------------------------------------------------------------------------

def _make_env(hostname: str, indexer_pw: str, dashboard_pw: str) -> list[dict]:
    return [
        {"name": "WAZUH_HOSTNAME",     "value": hostname},
        {"name": "INDEXER_PASSWORD",   "value": indexer_pw},
        {"name": "DASHBOARD_PASSWORD", "value": dashboard_pw},
    ]


def _find_stack(base: str, token: str, name: str) -> dict | None:
    stacks = _api_get(base, token, "stacks")
    return next((s for s in stacks if s["Name"] == name), None)


def deploy_stack(base: str, token: str, ep_id: int, name: str,
                 compose: str, env: list[dict]) -> dict:
    """Create or update a Portainer stack from a compose string."""
    existing = _find_stack(base, token, name)
    if existing:
        stack_id = existing["Id"]
        print(f"    Stack '{name}' exists (id={stack_id}), updating...")
        result = _api_put(
            base, token,
            f"stacks/{stack_id}?endpointId={ep_id}",
            {"stackFileContent": compose, "env": env, "prune": False},
        )
    else:
        print(f"    Creating stack '{name}'...")
        # No timeout: Portainer pulls images synchronously before returning
        result = _api_post(
            base, token,
            f"stacks/create/standalone/string?endpointId={ep_id}",
            {"name": name, "stackFileContent": compose, "env": env},
            timeout=None,
        )
    return result


def delete_stack(base: str, token: str, name: str) -> None:
    stack = _find_stack(base, token, name)
    if not stack:
        print(f"    Stack '{name}' not found, nothing to delete.")
        return
    stack_id = stack["Id"]
    ep_id = stack.get("EndpointId", ENDPOINT_ID)
    _api_delete(base, token, f"stacks/{stack_id}?endpointId={ep_id}")
    print(f"    Stack '{name}' (id={stack_id}) deleted.")


def ensure_host_dirs(base: str, token: str, ep_id: int) -> None:
    """Create required host-side dirs on the Synology via a transient busybox container."""
    dirs = [
        "/volume1/docker/wazuh/certs",
        "/volume1/docker/wazuh/wazuh-indexer",
        "/volume1/docker/wazuh/wazuh-manager",
        "/volume1/docker/wazuh/wazuh-dashboard",
    ]
    cmd = ["mkdir", "-p"] + dirs
    print(f"    Ensuring host dirs exist via busybox container...")

    # Create container
    body = {
        "Image": "busybox:latest",
        "Cmd": cmd,
        "HostConfig": {
            "Binds": [f"{d}:{d}" for d in dirs],
            "AutoRemove": True,
        },
    }
    try:
        r = _api_post(base, token,
                      f"endpoints/{ep_id}/docker/containers/create",
                      body)
        container_id = r["Id"]
        # Start
        req = urllib.request.Request(
            f"{base}/api/endpoints/{ep_id}/docker/containers/{container_id}/start",
            data=b"{}",
            headers={"X-API-Key": token, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, context=_ssl_ctx(), timeout=15) as resp:
            resp.read()
        # Wait a moment for AutoRemove
        time.sleep(3)
        print("    Host dirs ready.")
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")
        # "already exists" is fine
        if "already exists" in body_text or e.code in (304, 409):
            print("    Host dirs already exist.")
        else:
            print(f"    Warning: could not create dirs via busybox: {e.code} {body_text[:200]}")
            print("    Continuing — ensure /volume1/docker/wazuh/* dirs exist on Synology manually.")


def wait_container_exited(base: str, token: str, ep_id: int,
                          container_name: str, timeout_s: int = 300) -> bool:
    """Poll until docker container reaches 'exited' state (or timeout)."""
    deadline = time.time() + timeout_s
    filters = json.dumps({"name": [container_name]})
    path = f"endpoints/{ep_id}/docker/containers/json?all=true&filters={urllib.request.quote(filters)}"
    print(f"    Waiting for container '{container_name}' to exit (timeout={timeout_s}s)...")
    while time.time() < deadline:
        containers = _api_get(base, token, path)
        if containers:
            state = containers[0].get("State", "").lower()
            print(f"      state={state}", end="\r")
            if state == "exited":
                # Check exit code
                exit_code = containers[0].get("Status", "")
                print(f"\n    Container exited with status: {exit_code}")
                return True
        time.sleep(5)
    print(f"\n    TIMEOUT waiting for {container_name} to exit.")
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy Wazuh single-node to Portainer")
    parser.add_argument("--endpoint-id", type=int, default=ENDPOINT_ID,
                        help=f"Portainer endpoint ID (default: {ENDPOINT_ID})")
    parser.add_argument("--hostname", default=HOSTNAME,
                        help=f"Reverse-proxy hostname (default: {HOSTNAME})")
    parser.add_argument("--indexer-password", required=True,
                        help="OpenSearch admin + kibanaserver password")
    parser.add_argument("--dashboard-password", required=True,
                        help="Wazuh dashboard API (wazuh-wui) password")
    parser.add_argument("--skip-certgen", action="store_true",
                        help="Skip cert generation (certs already present)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print compose/env without calling Portainer")
    args = parser.parse_args()

    compose_content  = COMPOSE_FILE.read_text()
    certgen_content  = CERTGEN_COMPOSE_FILE.read_text()
    env              = _make_env(args.hostname, args.indexer_password, args.dashboard_password)

    if args.dry_run:
        print("=== DRY RUN ===")
        print(f"Endpoint ID : {args.endpoint_id}")
        print(f"Hostname    : {args.hostname}")
        print(f"Stack name  : {STACK_NAME}")
        print(f"Certgen skip: {args.skip_certgen}")
        print()
        print("--- ENV VARS ---")
        for e in env:
            print(f"  {e['name']}={e['value']}")
        print()
        print("--- MAIN COMPOSE ---")
        print(compose_content)
        if not args.skip_certgen:
            print("--- CERTGEN COMPOSE ---")
            print(certgen_content)
        return

    base  = _keychain("portainer-url")
    token = _keychain("portainer-token")

    print(f"Portainer: {base}")
    print(f"Endpoint : {args.endpoint_id}")
    print()

    # -----------------------------------------------------------------------
    # Step 1: Certgen
    # -----------------------------------------------------------------------
    if not args.skip_certgen:
        print("[1/3] Deploying certgen stack (Docker will create host dirs automatically)...")
        deploy_stack(base, token, args.endpoint_id, CERTGEN_STACK_NAME, certgen_content, [])
        ok = wait_container_exited(base, token, args.endpoint_id, "wazuh-certgen", timeout_s=300)
        if not ok:
            sys.exit("Certgen container did not exit cleanly within 5 minutes. "
                     "Check Portainer logs for 'wazuh-certgen'.")
        print("[1/3] Cert generation done. Removing certgen stack...")
        delete_stack(base, token, CERTGEN_STACK_NAME)
        print()
    else:
        print("[1/3] Skipping certgen (--skip-certgen)")

    # -----------------------------------------------------------------------
    # Step 2: Deploy main Wazuh stack
    # -----------------------------------------------------------------------
    print(f"[2/3] Deploying '{STACK_NAME}' stack...")
    result = deploy_stack(base, token, args.endpoint_id, STACK_NAME, compose_content, env)
    stack_id = result.get("Id", "?")
    print(f"      Stack deployed — id={stack_id}")
    print()

    # -----------------------------------------------------------------------
    # Step 3: Summary
    # -----------------------------------------------------------------------
    print("[3/3] Deployment complete.")
    print()
    print(f"  Dashboard  : https://{args.hostname}")
    print( "  Credentials: admin / <your DASHBOARD_PASSWORD>")
    print()
    print("NPM Reverse Proxy (Nginx Proxy Manager):")
    print(f"  Domain   : {args.hostname}")
    print( "  Scheme   : http")
    print( "  Hostname : wazuh-dashboard")
    print( "  Port     : 5601")
    print()
    print("Note: First startup takes 2-5 minutes for OpenSearch to initialise.")
    print("      Check stack logs in Portainer for progress.")


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
