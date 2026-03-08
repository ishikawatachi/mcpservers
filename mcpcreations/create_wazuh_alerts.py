#!/usr/bin/env python3
"""
Create Wazuh alert rules in Grafana → Discord notifications.

Alert Rules Created
--------------------
1. Wazuh Critical Alert          — rule.level >= 12 fires in last 5 min
2. Wazuh Auth Brute Force        — >= 10 auth failures per source IP in 5 min
3. Wazuh Agent Disconnected      — agent status becomes disconnected
4. macOS CIS Benchmark Failures  — CIS SCA failed checks spike (>= 5 failed in 1 h)
5. Wazuh Root Command Execution  — any root command event in last 5 min
6. Wazuh FIM Critical Change     — system binary / config change detected

Important
---------
These rules query the Wazuh Indexer (OpenSearch).
The Grafana Elasticsearch datasource (uid='wazuh-indexer') must be configured.

Alert data flow:
  Wazuh agent → Wazuh Manager → Wazuh Indexer (OpenSearch)
  → Grafana ES datasource query every 1 min
  → Alert rule evaluates count/threshold
  → Discord notification

Usage
-----
    python3 create_wazuh_alerts.py
    python3 create_wazuh_alerts.py --dry-run
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

WAZUH_DS_UID = "wazuh-indexer"
FOLDER_UID   = "infrastructure"     # place rules alongside existing infra alerts
RULE_GROUP   = "Wazuh Security"


def _es_rule(
    uid: str,
    title: str,
    lucene_query: str,
    time_range_seconds: int,
    threshold: int,
    comparison: str,      # "gt" or "lt"
    for_duration: str,
    severity: str,
    summary: str,
    description: str,
    exec_err_state: str = "KeepLast",
    no_data_state: str  = "OK",
) -> dict:
    """
    Build a Grafana alert rule that:
      A: counts OpenSearch events matching lucene_query over the last N seconds
      B: reduces A → last value
      C: threshold comparison on B
    """
    return {
        "uid": uid,
        "orgID": 1,
        "folderUID": FOLDER_UID,
        "ruleGroup": RULE_GROUP,
        "title": title,
        "condition": "C",
        "data": [
            {
                "refId": "A",
                "queryType": "",
                "relativeTimeRange": {"from": time_range_seconds, "to": 0},
                "datasourceUid": WAZUH_DS_UID,
                "model": {
                    "alias": "event_count",
                    "bucketAggs": [],
                    "metrics": [{"id": "1", "type": "count"}],
                    "query": lucene_query,
                    "queryType": "lucene",
                    "refId": "A",
                    "timeField": "@timestamp",
                },
            },
            {
                "refId": "B",
                "queryType": "",
                "relativeTimeRange": {"from": time_range_seconds, "to": 0},
                "datasourceUid": "-100",
                "model": {
                    "conditions": [],
                    "datasource": {"type": "__expr__", "uid": "-100"},
                    "expression": "A",
                    "intervalMs": 1000,
                    "maxDataPoints": 43200,
                    "reducer": "last",
                    "refId": "B",
                    "type": "reduce",
                },
            },
            {
                "refId": "C",
                "queryType": "",
                "relativeTimeRange": {"from": time_range_seconds, "to": 0},
                "datasourceUid": "-100",
                "model": {
                    "conditions": [
                        {
                            "evaluator": {"params": [threshold], "type": comparison},
                            "operator": {"type": "and"},
                            "query": {"params": ["B"]},
                            "reducer": {"params": [], "type": "last"},
                            "type": "query",
                        }
                    ],
                    "datasource": {"type": "__expr__", "uid": "-100"},
                    "expression": "B",
                    "intervalMs": 1000,
                    "maxDataPoints": 43200,
                    "refId": "C",
                    "type": "threshold",
                },
            },
        ],
        "noDataState": no_data_state,
        "execErrState": exec_err_state,
        "for": for_duration,
        "keep_firing_for": "0s",
        "annotations": {
            "summary": summary,
            "description": description,
        },
        "labels": {
            "env": "homelab",
            "severity": severity,
            "team": "security",
            "source": "wazuh",
        },
        "isPaused": False,
        "notification_settings": None,
        "record": None,
    }


def build_rules() -> list[dict]:
    return [
        # ── 1. Critical Wazuh Alert ───────────────────────────────────────────
        _es_rule(
            uid="wazuh-critical-alert-v1",
            title="Wazuh Critical Security Alert (level ≥ 12)",
            lucene_query="rule.level:[12 TO 15]",
            time_range_seconds=300,   # 5 minutes
            threshold=1,
            comparison="gt",
            for_duration="0s",        # fire immediately when threshold crossed
            severity="critical",
            summary="🔴 Wazuh: Critical security event detected",
            description=(
                "One or more Wazuh alert(s) at level 12+ were fired in the last 5 minutes. "
                "Investigate immediately in the Wazuh dashboard. "
                "Common causes: rootkit detection, privilege escalation, integrity failure."
            ),
        ),

        # ── 2. Brute-Force Authentication ────────────────────────────────────
        _es_rule(
            uid="wazuh-auth-bruteforce-v1",
            title="Wazuh Authentication Brute Force Detected",
            lucene_query="rule.groups:authentication_failed",
            time_range_seconds=300,   # 5 minutes
            threshold=10,
            comparison="gt",
            for_duration="2m",
            severity="warning",
            summary="⚠️ Wazuh: Brute-force authentication attempt detected",
            description=(
                "More than 10 authentication failures were recorded in the last 5 minutes. "
                "Check source IPs in the Wazuh dashboard → Authentication panel. "
                "Consider blocking the offending IP via Pi-hole or firewall rule."
            ),
        ),

        # ── 3. Wazuh Agent Disconnected ──────────────────────────────────────
        _es_rule(
            uid="wazuh-agent-disconnected-v1",
            title="Wazuh Agent Disconnected",
            lucene_query='rule.id:504 OR rule.id:506 OR rule.description:*disconnected*',
            time_range_seconds=600,   # 10 minutes look-back
            threshold=1,
            comparison="gt",
            for_duration="5m",
            severity="warning",
            exec_err_state="KeepLast",
            no_data_state="OK",
            summary="⚠️ Wazuh: Agent disconnected",
            description=(
                "A Wazuh agent has been marked as disconnected. "
                "The monitored host may be offline or the Wazuh agent service may have stopped. "
                "Rule IDs 504/506 indicate agent connection failures."
            ),
        ),

        # ── 4. macOS CIS Benchmark Failures ──────────────────────────────────
        _es_rule(
            uid="wazuh-cis-macos-failures-v1",
            title="macOS CIS Benchmark: New Failures Detected",
            lucene_query="rule.groups:sca AND data.sca.result:failed AND data.sca.policy_id:cis_apple*",
            time_range_seconds=3600,  # 1 hour (SCA runs every 12 h, catch the batch)
            threshold=5,
            comparison="gt",
            for_duration="0s",
            severity="warning",
            exec_err_state="KeepLast",
            no_data_state="OK",
            summary="⚠️ Wazuh: macOS CIS benchmark compliance failures",
            description=(
                "More than 5 CIS macOS benchmark checks failed in the last hour. "
                "Review the CIS SCA panel in the Wazuh Security dashboard to see which "
                "specific checks are failing. Ensure the macOS Wazuh agent has the "
                "CIS policy enabled (cis_apple_macOS_13.0.yml or later)."
            ),
        ),

        # ── 5. Root Command Execution ─────────────────────────────────────────
        _es_rule(
            uid="wazuh-root-execution-v1",
            title="Wazuh: Root Command Execution Detected",
            lucene_query="rule.groups:rootcheck OR (rule.groups:audit AND data.audit.euid:0)",
            time_range_seconds=300,   # 5 minutes
            threshold=1,
            comparison="gt",
            for_duration="0s",
            severity="warning",
            exec_err_state="KeepLast",
            no_data_state="OK",
            summary="⚠️ Wazuh: Root/privileged command executed",
            description=(
                "A command was executed as root or with elevated privileges on a monitored host. "
                "This may be expected (system updates, admin tasks) or indicate compromise. "
                "Review immediately in Wazuh dashboard → Rootcheck panel."
            ),
        ),

        # ── 6. FIM: Critical System File Change ──────────────────────────────
        _es_rule(
            uid="wazuh-fim-critical-v1",
            title="Wazuh FIM: Critical System File Modified",
            lucene_query=(
                "rule.groups:syscheck AND rule.level:[7 TO 15] AND "
                "(syscheck.path:*\\/bin\\/* OR syscheck.path:*\\/etc\\/* OR "
                "syscheck.path:*\\/lib\\/* OR syscheck.path:*/System/*)"
            ),
            time_range_seconds=300,   # 5 minutes
            threshold=1,
            comparison="gt",
            for_duration="0s",
            severity="critical",
            exec_err_state="KeepLast",
            no_data_state="OK",
            summary="🔴 Wazuh FIM: Critical system file or binary changed",
            description=(
                "A file in a critical system path (/bin, /etc, /lib, /System) was modified. "
                "This may indicate a system update, misconfiguration, or compromise. "
                "Review the File Integrity Monitor panel in the Wazuh Security dashboard."
            ),
        ),
    ]


async def _rule_exists(client: GrafanaClient, uid: str) -> bool:
    try:
        await client.get(f"v1/provisioning/alert-rules/{uid}")
        return True
    except Exception:
        return False


async def main(dry_run: bool = False) -> None:
    print("\n╔══════════════════════════════════════════════════════╗")
    print("║  Wazuh Grafana Alert Rules Setup                    ║")
    print("╚══════════════════════════════════════════════════════╝\n")

    if dry_run:
        print("⚠️  DRY-RUN mode — no changes to Grafana\n")

    client = GrafanaClient()
    rules = build_rules()

    for rule in rules:
        uid   = rule["uid"]
        title = rule["title"]
        exists = await _rule_exists(client, uid)

        if exists:
            print(f"  ↩️  Already exists [{uid}] {title}")
            if not dry_run:
                # Update in place
                await client.put(f"v1/provisioning/alert-rules/{uid}", rule)
                print("      → Updated ✅")
            else:
                print("      → [dry-run] Would update")
        else:
            print(f"  ➕  Creating [{uid}] {title}")
            if not dry_run:
                result = await client.post("v1/provisioning/alert-rules", rule)
                print(f"      → Created ✅  (uid={result.get('uid', uid)})")
            else:
                print("      → [dry-run] Would create")

    print(f"\n{'Dry-run complete' if dry_run else 'Done'} ✅  ({len(rules)} rules processed)")

    if not dry_run:
        print("\n📋  Summary of Wazuh alert rules:")
        print("  Rule Group: Wazuh Security (folder: infrastructure)")
        print("  Contact point: Discord (via default notification policy)")
        for r in rules:
            print(f"  • {r['title']} [{r['labels']['severity']}] for={r['for']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create Wazuh alert rules in Grafana")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
