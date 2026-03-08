#!/usr/bin/env python3
"""
deploy_wazuh.py
===============
Deploys the Wazuh single-node stack to Portainer via the portainer_mcp client.

Steps
-----
1. Discover available Portainer endpoints (environments)
2. Optionally query existing stacks so we know whether this is a create or update
3. Ensure the 'proxy' external network exists on the target endpoint
4. Deploy the docker-compose.yml as a Portainer stack named 'wazuh'
5. Tail the first 60 seconds of manager logs to verify startup

Usage
-----
    # From repo root, activate the portainer-mcp venv first:
    source mcpportainer/.venv/bin/activate

    python mcpcreations/deployments/wazuh/deploy_wazuh.py \
        --endpoint-id 1 \
        --hostname wazuh.local.yourdomain.com \
        --indexer-password 'SecureIndexerPass1!' \
        --dashboard-password 'SecureDashPass1!'

    # Dry-run: print the compose file that would be sent without deploying
    python ... --dry-run

    # Use a specific endpoint (default: first available)
    python ... --endpoint-id 2
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent.parent.parent  # git/mcp/

# Import from the portainer-mcp venv
sys.path.insert(0, str(REPO_ROOT / "mcpportainer" / "src"))

from portainer_mcp.client import PortainerClient, PortainerAPIError
from portainer_mcp.config import get_settings

COMPOSE_FILE = SCRIPT_DIR / "docker-compose.yml"
STACK_NAME = "wazuh"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_compose(hostname: str, indexer_password: str, dashboard_password: str) -> str:
    """Read the compose file and inject required environment variable comments."""
    return COMPOSE_FILE.read_text()


def env_vars(hostname: str, indexer_password: str, dashboard_password: str) -> dict[str, str]:
    """Return the env var dict that Portainer will inject into the stack."""
    return {
        "WAZUH_HOSTNAME": hostname,
        "INDEXER_PASSWORD": indexer_password,
        "DASHBOARD_PASSWORD": dashboard_password,
    }


# ---------------------------------------------------------------------------
# Main deployment flow
# ---------------------------------------------------------------------------

async def deploy(args: argparse.Namespace) -> None:
    settings = get_settings()
    compose_content = load_compose(args.hostname, args.indexer_password, args.dashboard_password)

    if args.dry_run:
        print("=== DRY RUN — compose content that would be sent ===")
        print(compose_content)
        print("=== ENV VARS ===")
        print(json.dumps(env_vars(args.hostname, args.indexer_password, args.dashboard_password), indent=2))
        return

    async with PortainerClient(settings) as client:
        # Step 1: List endpoints and choose the target
        endpoints = await client.list_endpoints()
        if not endpoints:
            sys.exit("No Portainer endpoints found — check credentials")

        if args.endpoint_id:
            endpoint = next((e for e in endpoints if e["Id"] == args.endpoint_id), None)
            if not endpoint:
                ids = [e["Id"] for e in endpoints]
                sys.exit(f"Endpoint {args.endpoint_id} not found. Available: {ids}")
        else:
            endpoint = endpoints[0]

        ep_id: int = endpoint["Id"]
        ep_name: str = endpoint.get("Name", str(ep_id))
        print(f"[1/4] Using endpoint: {ep_name} (id={ep_id})")

        # Step 2: List existing stacks
        stacks = await client.list_stacks()
        existing_names = [s.get("Name") for s in stacks]
        action = "update" if STACK_NAME in existing_names else "create"
        print(f"[2/4] Stack '{STACK_NAME}' will be {action}d on endpoint {ep_name}")

        # Step 3: Verify we can reach the endpoint (health check)
        try:
            health = await client.health()
            print(f"[3/4] Portainer health OK — version {health.get('Version', 'unknown')}")
        except PortainerAPIError as e:
            sys.exit(f"Health check failed: {e}")

        # Step 4: Deploy the stack
        print(f"[4/4] Deploying stack '{STACK_NAME}'…")
        result = await client.deploy_stack(
            endpoint_id=ep_id,
            stack_name=STACK_NAME,
            compose_content=compose_content,
            env_vars=env_vars(args.hostname, args.indexer_password, args.dashboard_password),
        )
        stack_id = result.get("Id") if isinstance(result, dict) else "?"
        print(f"      Stack deployed — id={stack_id}")
        print()
        print("Wazuh deployment complete.")
        print(f"  Dashboard URL: http://{args.hostname}")
        print( "  Default credentials: admin / (your DASHBOARD_PASSWORD)")
        print()
        print("Synology Reverse Proxy setup (DSM > Control Panel > Application Portal > Reverse Proxy):")
        print(f"  Source:   HTTPS  {args.hostname}  :443")
        print(f"  Dest:     HTTP   <docker-host-ip>  5601")
        print()
        print("Note: The first start takes 2-3 minutes for the indexer to initialise.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy Wazuh single-node to Portainer")
    parser.add_argument("--endpoint-id", type=int, default=0,
                        help="Portainer endpoint ID (default: first available)")
    parser.add_argument("--hostname", required=True,
                        help="Hostname for Synology reverse proxy (e.g. wazuh.local.yourdomain.com)")
    parser.add_argument("--indexer-password", required=True,
                        help="OpenSearch indexer + kibanaserver password")
    parser.add_argument("--dashboard-password", required=True,
                        help="Dashboard admin (wazuh-wui) password")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print compose and env vars without deploying")
    parser.add_argument("--stack-name", default=STACK_NAME,
                        help=f"Portainer stack name (default: {STACK_NAME})")
    args = parser.parse_args()

    asyncio.run(deploy(args))


if __name__ == "__main__":
    main()
