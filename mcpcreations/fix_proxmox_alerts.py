#!/usr/bin/env python3
"""
Fix Proxmox / pve_exporter Grafana alert rules.

Problems being fixed
--------------------
1. "Proxmox Node Down" (uid: cfeozyn9eayo0e)
   - for: 2m  → 5m   (stops false alarms on brief restarts / maintenance)
   - execErrState: Error → KeepLast (stops false alarms when pve_exporter
     itself has a TCP timeout reaching Proxmox — the scrape fails, but that
     doesn't mean the node is down)
   - noDataState: NoData → KeepLast  (same rationale)

2. "Prometheus Target Down" (uid: prom-target-down-v2)
   - Exclude the pve job: up{job!="pve"} == 0   (pve_exporter connectivity
     failures are handled by the dedicated pve_exporter alert below)
   - execErrState: Error → KeepLast

3. Add NEW alert: "pve_exporter Unreachable" (uid: pve-exporter-unreachable-v1)
   - Fires when up{job="pve"} == 0 for 5m
   - severity: warning (not critical — this is a connectivity issue, not
     necessarily a node outage)
   - noDataState: OK (if the exporter just started, no data is fine)
   - execErrState: KeepLast

Usage
-----
    python3 fix_proxmox_alerts.py
    python3 fix_proxmox_alerts.py --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

sys.path.insert(
    0,
    "/Users/nicolas/Library/CloudStorage/ProtonDrive-serialinsert@proton.me"
    "/git/mcp/grafanamcp/src",
)
from grafana_mcp.client import GrafanaClient

PROM_DS_UID = "ceb67eiok1qf4d"

PROXMOX_NODE_DOWN_UID = "cfeozyn9eayo0e"
TARGET_DOWN_UID = "prom-target-down-v2"
PVE_EXPORTER_UID = "pve-exporter-unreachable-v1"


# ─── helpers ──────────────────────────────────────────────────────────────────

def _strip_server_fields(rule: dict) -> dict:
    """Remove read-only server-managed fields before a PUT."""
    for key in ("provenance", "updated", "id"):
        rule.pop(key, None)
    return rule


async def fix_proxmox_node_down(client: GrafanaClient, dry_run: bool = False) -> None:
    """Increase 'for' to 5m and switch execErrState to KeepLast."""
    print("Fetching Proxmox Node Down alert …")
    rule = await client.get(f"v1/provisioning/alert-rules/{PROXMOX_NODE_DOWN_UID}")

    before = {"for": rule.get("for"), "execErrState": rule.get("execErrState"),
               "noDataState": rule.get("noDataState")}

    rule["for"] = "5m"
    rule["execErrState"] = "KeepLast"
    rule["noDataState"] = "KeepLast"

    # Update the description to reflect the new behaviour
    rule.setdefault("annotations", {})
    rule["annotations"]["description"] = (
        "pve_up metric has been 0 for 5 consecutive minutes on node "
        "{{ $labels.node }}. Check {{ $externalURL }}. "
        "(Alert suppressed during scrape errors to reduce false positives.)"
    )

    print(f"  Before: {before}")
    print(f"  After : for=5m  execErrState=KeepLast  noDataState=KeepLast")

    if not dry_run:
        result = await client.put(
            f"v1/provisioning/alert-rules/{PROXMOX_NODE_DOWN_UID}",
            _strip_server_fields(rule),
        )
        print(f"  ✅  Updated: {result.get('uid', result)}\n")
    else:
        print("  [dry-run] skipping PUT\n")


async def fix_prometheus_target_down(client: GrafanaClient, dry_run: bool = False) -> None:
    """Exclude pve job; switch execErrState to KeepLast."""
    print("Fetching Prometheus Target Down alert …")
    rule = await client.get(f"v1/provisioning/alert-rules/{TARGET_DOWN_UID}")

    # Rewrite the Prometheus query to exclude the pve job
    for step in rule.get("data", []):
        if step["refId"] == "A" and step.get("datasourceUid") == PROM_DS_UID:
            old_expr = step["model"].get("expr", "")
            step["model"]["expr"] = 'up{job!="pve"} == 0'
            print(f"  Rewritten expr:  {old_expr!r}  →  'up{{job!=\"pve\"}} == 0'")

    rule["execErrState"] = "KeepLast"
    rule.setdefault("annotations", {})
    rule["annotations"]["description"] = (
        "Scrape target {{ $labels.job }} / {{ $labels.instance }} has been "
        "unreachable for {{ humanizeDuration $for }}. "
        "(pve_exporter connectivity is tracked by a dedicated alert.)"
    )

    print(f"  execErrState → KeepLast")
    if not dry_run:
        result = await client.put(
            f"v1/provisioning/alert-rules/{TARGET_DOWN_UID}",
            _strip_server_fields(rule),
        )
        print(f"  ✅  Updated: {result.get('uid', result)}\n")
    else:
        print("  [dry-run] skipping PUT\n")


async def create_pve_exporter_unreachable(
    client: GrafanaClient, dry_run: bool = False
) -> None:
    """Create a new targeted alert for pve_exporter connectivity failures."""
    print("Creating pve_exporter Unreachable alert …")

    # Check if it already exists
    try:
        existing = await client.get(f"v1/provisioning/alert-rules/{PVE_EXPORTER_UID}")
        print(f"  ℹ️  Alert already exists (uid={PVE_EXPORTER_UID}). Skipping creation.\n")
        return
    except Exception:
        pass  # expected — doesn't exist yet

    rule = {
        "uid": PVE_EXPORTER_UID,
        "orgID": 1,
        "folderUID": "infrastructure",
        "ruleGroup": "Proxmox",
        "title": "pve_exporter Cannot Reach Proxmox",
        "condition": "C",
        "data": [
            {
                "refId": "A",
                "queryType": "",
                "relativeTimeRange": {"from": 600, "to": 0},
                "datasourceUid": PROM_DS_UID,
                "model": {
                    "expr": 'up{job="pve"}',
                    "instant": True,
                    "intervalMs": 1000,
                    "maxDataPoints": 43200,
                    "refId": "A",
                },
            },
            {
                "refId": "C",
                "queryType": "",
                "relativeTimeRange": {"from": 600, "to": 0},
                "datasourceUid": "-100",
                "model": {
                    "conditions": [
                        {
                            "evaluator": {"params": [1], "type": "lt"},
                            "operator": {"type": "and"},
                            "query": {"params": ["A"]},
                            "reducer": {"params": [], "type": "last"},
                            "type": "query",
                        }
                    ],
                    "datasource": {"type": "__expr__", "uid": "-100"},
                    "expression": "A",
                    "intervalMs": 1000,
                    "maxDataPoints": 43200,
                    "refId": "C",
                    "type": "classic_conditions",
                },
            },
        ],
        "noDataState": "OK",          # no data → exporter just started, not an alert
        "execErrState": "KeepLast",   # if Grafana itself errors, keep last evaluation
        "for": "5m",
        "keep_firing_for": "0s",
        "annotations": {
            "summary": "pve_exporter cannot reach Proxmox ({{ $labels.instance }})",
            "description": (
                "The Prometheus scrape of pve_exporter has been failing for 5 minutes. "
                "Either pve_exporter is down/restarting, or it is unable to reach the "
                "Proxmox API at pm.local.defaultvaluation.com. "
                "Check container logs: docker logs pve_exporter"
            ),
        },
        "labels": {
            "env": "homelab",
            "severity": "warning",
            "team": "infra",
            "component": "pve_exporter",
        },
        "isPaused": False,
        "notification_settings": None,
        "record": None,
    }

    print(
        "  New rule: pve_exporter Unreachable | for=5m | "
        "execErrState=KeepLast | noDataState=OK"
    )
    if not dry_run:
        result = await client.post("v1/provisioning/alert-rules", rule)
        print(f"  ✅  Created: {result.get('uid', result)}\n")
    else:
        print("  [dry-run] skipping POST\n")


# ─── main ─────────────────────────────────────────────────────────────────────

async def main(dry_run: bool = False) -> None:
    client = GrafanaClient()

    print("\n╔══════════════════════════════════════════════════════╗")
    print("║  Proxmox / pve_exporter Alert Rule Improvements     ║")
    print("╚══════════════════════════════════════════════════════╝\n")

    if dry_run:
        print("⚠️  DRY-RUN mode — no changes will be written\n")

    await fix_proxmox_node_down(client, dry_run)
    await fix_prometheus_target_down(client, dry_run)
    await create_pve_exporter_unreachable(client, dry_run)

    print("Done ✅")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fix Proxmox alert rules to reduce false positives"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change without writing to Grafana",
    )
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
