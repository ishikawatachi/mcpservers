#!/usr/bin/env python3
"""
Deploy the Wazuh Security Operations dashboard to Grafana.

Prerequisites
-------------
  1. Run create_wazuh_datasource.py first (or confirm the Wazuh Indexer
     datasource already exists in Grafana with uid='wazuh-indexer').
  2. The dashboard JSON (wazuh_dashboard.json) must be in the same directory.

Usage
-----
    python3 create_wazuh_dashboard.py
    python3 create_wazuh_dashboard.py --dry-run
    python3 create_wazuh_dashboard.py --folder-uid security   # place in 'security' folder
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(
    0,
    "/Users/nicolas/Library/CloudStorage/ProtonDrive-serialinsert@proton.me"
    "/git/mcp/grafanamcp/src",
)
from grafana_mcp.client import GrafanaClient

DASHBOARD_FILE = Path(__file__).parent / "wazuh_dashboard.json"
WAZUH_DS_UID   = "wazuh-indexer"  # must match create_wazuh_datasource.py


def _inject_datasource(dashboard: dict, ds_uid: str) -> dict:
    """Replace the ${DS_WAZUH_INDEXER} placeholder with the actual UID."""
    raw = json.dumps(dashboard)
    raw = raw.replace("${DS_WAZUH_INDEXER}", ds_uid)
    return json.loads(raw)


async def _verify_datasource(client: GrafanaClient) -> bool:
    """Check that the Wazuh datasource is registered in Grafana."""
    try:
        ds_list = await client.get("datasources")
        for ds in ds_list:
            if ds.get("uid") == WAZUH_DS_UID:
                print(f"  ✅  Wazuh datasource found: '{ds['name']}' (uid={WAZUH_DS_UID})")
                return True
        print(f"  ⚠️  Datasource uid='{WAZUH_DS_UID}' NOT found in Grafana.")
        print("      Run create_wazuh_datasource.py first, then retry.")
        return False
    except Exception as exc:
        print(f"  ⚠️  Could not verify datasource: {exc}")
        return False


async def main(folder_uid: str | None = None, dry_run: bool = False) -> None:
    print("\n╔══════════════════════════════════════════════════════╗")
    print("║  Wazuh Security Dashboard Deployment                ║")
    print("╚══════════════════════════════════════════════════════╝\n")

    if not DASHBOARD_FILE.exists():
        print(f"❌  Dashboard file not found: {DASHBOARD_FILE}")
        sys.exit(1)

    with DASHBOARD_FILE.open() as f:
        dashboard = json.load(f)

    dashboard = _inject_datasource(dashboard, WAZUH_DS_UID)

    client = GrafanaClient()

    print("Verifying Wazuh datasource …")
    ds_ok = await _verify_datasource(client)
    if not ds_ok and not dry_run:
        sys.exit(1)

    # Resolve target folder
    target_folder = folder_uid
    if not target_folder:
        # Use existing 'infrastructure' folder
        folders = await client.get("folders", limit="50")
        for f in folders:
            if f.get("uid") == "infrastructure":
                target_folder = "infrastructure"
                break
        if not target_folder:
            print("  ⚠️  'infrastructure' folder not found — deploying to root.")

    print(f"\nDeploying '{dashboard['title']}' …")
    print(f"  UID: {dashboard.get('uid', '(new)')}")
    print(f"  Folder: {target_folder or 'root'}")

    if dry_run:
        print("\n⚠️  DRY-RUN — no changes written to Grafana\n")
        print("  Dashboard JSON summary:")
        print(f"    panels   : {len(dashboard.get('panels', []))}")
        print(f"    variables: {len(dashboard.get('templating', {}).get('list', []))}")
        print("Done ✅")
        return

    body = {
        "dashboard": dashboard,
        "message": "Wazuh Security dashboard deployed via MCP",
        "overwrite": True,
    }
    if target_folder:
        body["folderUid"] = target_folder

    result = await client.post("dashboards/db", body)
    status = result.get("status", "?")
    url    = result.get("url", "")
    print(f"  ✅  {status.upper()} — {url}")
    print("\nDone ✅")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy Wazuh dashboard to Grafana")
    parser.add_argument("--folder-uid", default=None, help="Grafana folder UID")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    asyncio.run(main(folder_uid=args.folder_uid, dry_run=args.dry_run))
