#!/usr/bin/env python3
"""
Add the Wazuh Indexer (OpenSearch) data source to Grafana.

The Wazuh Indexer is OpenSearch-compatible; this script registers it as an
Elasticsearch-type datasource (Grafana's built-in ES plugin works with OpenSearch).

Environment variables / Keychain accounts
------------------------------------------
  WAZUH_INDEXER_URL      URL of the Wazuh Indexer  (default: https://wazuh-indexer.local.defaultvaluation.com:9200)
  WAZUH_INDEXER_USER     Basic-auth username        (default: admin)
  WAZUH_INDEXER_PASS     Basic-auth password        (required — no default)

Usage
-----
    export WAZUH_INDEXER_PASS="<your-password>"
    python3 create_wazuh_datasource.py

    # Dry-run (just validates credentials, no changes to Grafana):
    python3 create_wazuh_datasource.py --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(
    0,
    "/Users/nicolas/Library/CloudStorage/ProtonDrive-serialinsert@proton.me"
    "/git/mcp/grafanamcp/src",
)
from grafana_mcp.client import GrafanaClient

DATASOURCE_NAME = "Wazuh Indexer"
DATASOURCE_UID  = "wazuh-indexer"   # stable UID for dashboard references

DEFAULT_URL  = "https://wazuh-indexer.local.defaultvaluation.com:9200"
DEFAULT_USER = "admin"
INDEX_PATTERN = "wazuh-alerts-*"
TIME_FIELD    = "@timestamp"


async def _datasource_exists(client: GrafanaClient) -> dict | None:
    """Return the existing datasource dict if found, else None."""
    datasources = await client.get("datasources")
    for ds in datasources:
        if ds.get("uid") == DATASOURCE_UID or ds.get("name") == DATASOURCE_NAME:
            return ds
    return None


async def create_or_update_datasource(
    client: GrafanaClient,
    url: str,
    user: str,
    password: str,
    dry_run: bool = False,
) -> None:
    """POST (create) or PUT (update) the Wazuh datasource in Grafana."""

    payload = {
        "uid": DATASOURCE_UID,
        "name": DATASOURCE_NAME,
        "type": "elasticsearch",
        "url": url,
        "access": "proxy",
        "basicAuth": True,
        "basicAuthUser": user,
        "secureJsonData": {"basicAuthPassword": password},
        "jsonData": {
            "index": INDEX_PATTERN,
            "timeField": TIME_FIELD,
            "esVersion": "8.0.0",    # OpenSearch is ES-7/8 API-compatible
            "maxConcurrentShardRequests": 5,
            "logLevelField": "rule.level",
            "logMessageField": "rule.description",
            "tlsSkipVerify": True,   # Wazuh self-signed cert is common
        },
        "isDefault": False,
    }

    existing = await _datasource_exists(client)

    if dry_run:
        action = "UPDATE" if existing else "CREATE"
        print(f"  [dry-run] Would {action} datasource '{DATASOURCE_NAME}'")
        print(f"  Payload: {json.dumps({k: v for k, v in payload.items() if k != 'secureJsonData'}, indent=4)}")
        return

    if existing:
        ds_id = existing["id"]
        result = await client.put(f"datasources/{ds_id}", payload)
        print(f"  ✅  Updated existing datasource (id={ds_id}): {result.get('message', result)}")
    else:
        result = await client.post("datasources", payload)
        print(f"  ✅  Created datasource: {result.get('message', result)}")
        print(f"      UID: {result.get('datasource', {}).get('uid', DATASOURCE_UID)}")


async def main(dry_run: bool = False) -> None:
    url      = os.environ.get("WAZUH_INDEXER_URL", DEFAULT_URL)
    user     = os.environ.get("WAZUH_INDEXER_USER", DEFAULT_USER)
    password = os.environ.get("WAZUH_INDEXER_PASS", "")

    if not password and not dry_run:
        print("❌  WAZUH_INDEXER_PASS environment variable is required.")
        print("    Run:  export WAZUH_INDEXER_PASS='<your-admin-password>'")
        sys.exit(1)

    print("\n╔══════════════════════════════════════════════════════╗")
    print("║  Wazuh Indexer Datasource Setup                     ║")
    print("╚══════════════════════════════════════════════════════╝\n")
    print(f"  URL   : {url}")
    print(f"  Index : {INDEX_PATTERN}")
    print(f"  User  : {user}")
    print(f"  UID   : {DATASOURCE_UID}")

    if dry_run:
        print("\n⚠️  DRY-RUN mode — no changes to Grafana\n")

    client = GrafanaClient()
    await create_or_update_datasource(client, url, user, password, dry_run)
    print("\nDone ✅")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Register the Wazuh Indexer as a Grafana datasource"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
