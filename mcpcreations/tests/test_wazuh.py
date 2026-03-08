#!/usr/bin/env python3
"""
Test Suite: Wazuh Security Integration
=======================================
Validates that the Wazuh integration components are correctly
configured in Grafana:

  1. Wazuh Indexer datasource is registered (uid='wazuh-indexer')
  2. Wazuh Security Operations dashboard exists
  3. All 6 Wazuh alert rules are present with correct settings
  4. Wazuh alert rules route to Discord (via default policy)
  5. Alert rule configurations match the design intent

Run order:
    # Before: confirm no Wazuh integration exists yet
    python3 tests/test_wazuh.py --phase before

    # Run the setup scripts:
    #   python3 create_wazuh_datasource.py
    #   python3 create_wazuh_dashboard.py
    #   python3 create_wazuh_alerts.py

    # After: confirm everything is correctly deployed
    python3 tests/test_wazuh.py --phase after
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent.parent / "grafanamcp" / "src"),
)
from grafana_mcp.client import GrafanaClient

WAZUH_DS_UID        = "wazuh-indexer"
WAZUH_DASHBOARD_UID = "wazuh-security-v1"
WAZUH_RULE_GROUP    = "Wazuh Security"

EXPECTED_RULE_UIDS = {
    "wazuh-critical-alert-v1",
    "wazuh-auth-bruteforce-v1",
    "wazuh-agent-disconnected-v1",
    "wazuh-cis-macos-failures-v1",
    "wazuh-root-execution-v1",
    "wazuh-fim-critical-v1",
}

EXPECTED_RULE_META = {
    "wazuh-critical-alert-v1":     {"severity": "critical", "for": "0s"},
    "wazuh-auth-bruteforce-v1":    {"severity": "warning",  "for": "2m"},
    "wazuh-agent-disconnected-v1": {"severity": "warning",  "for": "5m"},
    "wazuh-cis-macos-failures-v1": {"severity": "warning",  "for": "0s"},
    "wazuh-root-execution-v1":     {"severity": "warning",  "for": "0s"},
    "wazuh-fim-critical-v1":       {"severity": "critical", "for": "0s"},
}


# ─── helpers ──────────────────────────────────────────────────────────────────

results: list[dict] = []
GREEN = "\033[92m"; RED = "\033[91m"; YELLOW = "\033[93m"; RESET = "\033[0m"
TICK  = f"{GREEN}✅{RESET}"; CROSS = f"{RED}❌{RESET}"; WARN = f"{YELLOW}⚠️ {RESET}"


def record(name: str, passed: bool, detail: str = "") -> None:
    results.append({"name": name, "passed": passed, "detail": detail})
    icon = TICK if passed else CROSS
    suffix = f"  {YELLOW}{detail}{RESET}" if detail and not passed else (f"  {detail}" if detail else "")
    print(f"  {icon}  {name}{suffix}")


# ─── before-phase tests ────────────────────────────────────────────────────────

async def test_before_phase(client: GrafanaClient) -> None:
    """Document that Wazuh integration is not yet deployed."""
    print(f"\n{YELLOW}━━ BEFORE: Confirm Wazuh integration not yet deployed ━━{RESET}")

    # Datasource should not exist yet
    datasources = await client.get("datasources")
    ds_found = any(d.get("uid") == WAZUH_DS_UID for d in datasources)
    record(
        f"Wazuh datasource (uid={WAZUH_DS_UID}) NOT yet configured",
        not ds_found,
        "already exists!" if ds_found else "correctly absent",
    )

    # Dashboard should not exist yet
    try:
        await client.get(f"dashboards/uid/{WAZUH_DASHBOARD_UID}")
        record(f"Wazuh dashboard NOT yet deployed", False, "already exists!")
    except Exception:
        record(f"Wazuh dashboard (uid={WAZUH_DASHBOARD_UID}) NOT yet deployed", True)

    # Alert rules should not exist yet
    all_rules = await client.get("v1/provisioning/alert-rules")
    wazuh_rules = {r["uid"] for r in all_rules if r.get("ruleGroup") == WAZUH_RULE_GROUP}
    record(
        "Wazuh alert rules NOT yet created",
        len(wazuh_rules) == 0,
        f"found: {wazuh_rules}" if wazuh_rules else "correctly absent",
    )


# ─── after-phase tests ─────────────────────────────────────────────────────────

async def test_after_phase(client: GrafanaClient) -> None:
    """Validate the complete Wazuh integration deployment."""

    # ── 1. Datasource ─────────────────────────────────────────────────────────
    print(f"\n  [1] Wazuh Indexer Datasource")
    datasources = await client.get("datasources")
    ds = next((d for d in datasources if d.get("uid") == WAZUH_DS_UID), None)
    record(f"  Datasource uid='{WAZUH_DS_UID}' registered", ds is not None)

    if ds:
        record("  Type is elasticsearch", ds.get("type") == "elasticsearch", f"got: {ds.get('type')}")
        record("  Name is 'Wazuh Indexer'", ds.get("name") == "Wazuh Indexer", f"got: {ds.get('name')}")
        json_data = ds.get("jsonData", {})
        record(
            "  Index pattern is wazuh-alerts-*",
            json_data.get("index", "").startswith("wazuh-alerts"),
            f"got: {json_data.get('index')}",
        )
        record(
            "  timeField is @timestamp",
            json_data.get("timeField") == "@timestamp",
            f"got: {json_data.get('timeField')}",
        )

    # ── 2. Dashboard ───────────────────────────────────────────────────────────
    print(f"\n  [2] Wazuh Security Operations Dashboard")
    try:
        data    = await client.get(f"dashboards/uid/{WAZUH_DASHBOARD_UID}")
        dashboard = data.get("dashboard", {})
        record("  Dashboard exists", True, f"title='{dashboard.get('title')}'")

        panels = dashboard.get("panels", [])
        record("  Has at least 10 panels", len(panels) >= 10, f"found {len(panels)}")

        # Check for key sections
        panel_titles = {p.get("title", "") for p in panels}
        record(
            "  Has alert count stat panels",
            any("Alert" in t or "Critical" in t for t in panel_titles),
        )
        record(
            "  Has CIS benchmark panel",
            any("CIS" in t or "macOS" in t or "Benchmark" in t for t in panel_titles),
        )
        record(
            "  Has FIM panel",
            any("FIM" in t or "File Integrity" in t or "File" in t for t in panel_titles),
        )

        # Check datasource references
        import json
        dash_json = json.dumps(dashboard)
        record(
            "  References Wazuh datasource uid",
            WAZUH_DS_UID in dash_json,
            "all panels should reference wazuh-indexer",
        )

        # Check for agent variable
        variables = dashboard.get("templating", {}).get("list", [])
        agent_var = any(v.get("name") == "agent" for v in variables)
        record("  Has 'agent' template variable", agent_var)

    except Exception as exc:
        record(f"  Dashboard ({WAZUH_DASHBOARD_UID}) accessible", False, str(exc))

    # ── 3. Alert Rules ─────────────────────────────────────────────────────────
    print(f"\n  [3] Wazuh Alert Rules ({len(EXPECTED_RULE_UIDS)} expected)")
    all_rules = await client.get("v1/provisioning/alert-rules")
    existing  = {r["uid"]: r for r in all_rules if r["uid"] in EXPECTED_RULE_UIDS}

    missing = EXPECTED_RULE_UIDS - set(existing.keys())
    record(
        f"  All {len(EXPECTED_RULE_UIDS)} rules present",
        len(missing) == 0,
        f"missing: {missing}" if missing else f"all {len(existing)} found",
    )

    for uid, meta in EXPECTED_RULE_META.items():
        if uid not in existing:
            continue
        rule = existing[uid]
        title = rule.get("title", uid)

        record(
            f"  [{uid}] severity={meta['severity']}",
            rule.get("labels", {}).get("severity") == meta["severity"],
            f"got: {rule.get('labels', {}).get('severity')}",
        )
        record(
            f"  [{uid}] for={meta['for']}",
            rule.get("for") == meta["for"],
            f"got: {rule.get('for')}",
        )
        record(
            f"  [{uid}] execErrState=KeepLast",
            rule.get("execErrState") == "KeepLast",
            f"got: {rule.get('execErrState')}",
        )
        # Confirm team=security label
        record(
            f"  [{uid}] team=security label",
            rule.get("labels", {}).get("team") == "security",
            f"got: {rule.get('labels', {}).get('team')}",
        )

    # ── 4. CIS macOS rule specifically ────────────────────────────────────────
    print(f"\n  [4] CIS macOS Benchmark Alert Details")
    cis_rule = existing.get("wazuh-cis-macos-failures-v1")
    if cis_rule:
        # Check the ES query contains CIS apple filter
        for step in cis_rule.get("data", []):
            if step["refId"] == "A":
                query = step["model"].get("query", "")
                record(
                    "  CIS query filters cis_apple* policy",
                    "cis_apple" in query or "cis_apple*" in query,
                    f"query: {query[:100]}",
                )
                record(
                    "  CIS query requires sca group",
                    "sca" in query,
                    f"query: {query[:100]}",
                )

    # ── 5. Notification policy ─────────────────────────────────────────────────
    print(f"\n  [5] Discord Notification Policy")
    policy = await client.get("v1/provisioning/policies")
    receiver = policy.get("receiver", "")
    record(
        "  Default receiver is Discord",
        "discord" in receiver.lower() or receiver == "Discord",
        f"receiver='{receiver}'",
    )
    # Group-by should include severity for good Discord messages
    group_by = policy.get("group_by", [])
    record(
        "  Policy groups by severity",
        "severity" in group_by,
        f"group_by={group_by}",
    )


# ─── summary ──────────────────────────────────────────────────────────────────

def print_summary() -> int:
    passed = sum(1 for r in results if r["passed"])
    total  = len(results)
    failed = total - passed
    pct    = int(passed / total * 100) if total else 0

    print(f"\n{'═'*55}")
    print(f"  Wazuh Tests: {passed}/{total} passed ({pct}%)")
    if failed:
        print(f"\n  Failed:")
        for r in results:
            if not r["passed"]:
                print(f"    ❌  {r['name']}" + (f"  [{r['detail']}]" if r["detail"] else ""))
    print(f"{'═'*55}\n")
    return 1 if failed else 0


# ─── main ─────────────────────────────────────────────────────────────────────

async def main(phase: str) -> int:
    client = GrafanaClient()

    print(f"\n{'─'*55}")
    print(f"  Wazuh Security Integration — Test Suite ({phase.upper()})")
    print(f"{'─'*55}")

    if phase == "before":
        await test_before_phase(client)
    elif phase == "after":
        await test_after_phase(client)
    else:
        print(f"Unknown phase: {phase!r}. Use --phase before|after")
        return 1

    return print_summary()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Wazuh Grafana integration")
    parser.add_argument(
        "--phase",
        choices=["before", "after"],
        default="after",
        help="Test phase: before (pre-setup) or after (post-setup validation)",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.phase)))
