#!/usr/bin/env python3
"""
Test Suite: Proxmox / pve_exporter Alert Rule Improvements
===========================================================
Before tests  — capture the state of alert rules BEFORE fix_proxmox_alerts.py runs
After tests   — validate that the improvements are correctly applied in Grafana

Run order:
    # 1. Capture baseline (run BEFORE applying fixes)
    python3 tests/test_proxmox_alerts.py --phase before

    # 2. Apply fixes
    python3 fix_proxmox_alerts.py

    # 3. Verify improvements (run AFTER applying fixes)
    python3 tests/test_proxmox_alerts.py --phase after

    # 4. Run both (useful for CI or re-verification)
    python3 tests/test_proxmox_alerts.py --phase verify
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent.parent / "grafanamcp" / "src"),
)
from grafana_mcp.client import GrafanaClient

# UIDs that must exist after applying fixes
PROXMOX_NODE_DOWN_UID   = "cfeozyn9eayo0e"
TARGET_DOWN_UID         = "prom-target-down-v2"
PVE_EXPORTER_UID        = "pve-exporter-unreachable-v1"
PROM_DS_UID             = "ceb67eiok1qf4d"


# ─── helpers ──────────────────────────────────────────────────────────────────

results: list[dict] = []

GREEN = "\033[92m"; RED = "\033[91m"; YELLOW = "\033[93m"; RESET = "\033[0m"
TICK  = f"{GREEN}✅{RESET}"; CROSS = f"{RED}❌{RESET}"; WARN = f"{YELLOW}⚠️ {RESET}"


def record(name: str, passed: bool, detail: str = "") -> None:
    results.append({"name": name, "passed": passed, "detail": detail})
    icon = TICK if passed else CROSS
    suffix = f"  {YELLOW}{detail}{RESET}" if detail and not passed else (f"  {detail}" if detail else "")
    print(f"  {icon}  {name}{suffix}")


def _get_pve_expr(rule: dict) -> str | None:
    """Return the Prometheus expression from step A in a rule."""
    for step in rule.get("data", []):
        if step["refId"] == "A" and step.get("datasourceUid") == PROM_DS_UID:
            return step["model"].get("expr", "")
    return None


# ─── before-phase tests ────────────────────────────────────────────────────────

async def test_before_phase(client: GrafanaClient) -> None:
    """Capture baseline state — what we expect to find BEFORE fixes are applied."""
    print(f"\n{YELLOW}━━ BEFORE: Baseline state (expected: unimproved settings) ━━{RESET}")

    try:
        rule = await client.get(f"v1/provisioning/alert-rules/{PROXMOX_NODE_DOWN_UID}")
        record(
            "Proxmox Node Down exists",
            True,
            f"title='{rule['title']}' for={rule['for']} execErrState={rule['execErrState']}",
        )
        # Document what we find (these will differ after the fix)
        for_ok = rule["for"] == "2m"
        record("  [baseline] for=2m (will be increased)", for_ok, rule["for"])
        err_ok = rule["execErrState"] == "Error"
        record("  [baseline] execErrState=Error (will be changed)", err_ok, rule["execErrState"])
    except Exception as exc:
        record(
            f"Proxmox Node Down ({PROXMOX_NODE_DOWN_UID}) is accessible",
            False,
            str(exc),
        )

    try:
        rule = await client.get(f"v1/provisioning/alert-rules/{TARGET_DOWN_UID}")
        expr = _get_pve_expr(rule) or "?"
        record(
            "Prometheus Target Down exists",
            True,
            f"expr='{expr}' execErrState={rule['execErrState']}",
        )
        # Baseline: the query covers ALL jobs (including pve)
        covers_pve = "pve" not in expr or "job!=" not in expr
        record("  [baseline] query includes pve job (will be excluded)", covers_pve, expr)
    except Exception as exc:
        record(f"Prometheus Target Down ({TARGET_DOWN_UID}) is accessible", False, str(exc))

    try:
        await client.get(f"v1/provisioning/alert-rules/{PVE_EXPORTER_UID}")
        record("  [baseline] pve_exporter Unreachable NOT yet created", False, "already exists!")
    except Exception:
        record("  [baseline] pve_exporter Unreachable does not exist yet", True)


# ─── after-phase tests ─────────────────────────────────────────────────────────

async def test_after_phase(client: GrafanaClient) -> None:
    """Validate that fix_proxmox_alerts.py applied all improvements correctly."""
    print(f"\n{GREEN}━━ AFTER: Verify improvements applied ━━{RESET}")

    # ── Proxmox Node Down ─────────────────────────────────────────────────────
    print("\n  [A] Proxmox Node Down (should have 5m window and KeepLast states)")
    try:
        rule = await client.get(f"v1/provisioning/alert-rules/{PROXMOX_NODE_DOWN_UID}")
        record("  Proxmox Node Down exists", True)

        record(
            "  for=5m (increased from 2m to reduce false alarms)",
            rule["for"] == "5m",
            f"got: {rule['for']}",
        )
        record(
            "  execErrState=KeepLast (no alarm on scrape errors)",
            rule["execErrState"] == "KeepLast",
            f"got: {rule['execErrState']}",
        )
        record(
            "  noDataState=KeepLast (no alarm if pve_up metric absent)",
            rule["noDataState"] == "KeepLast",
            f"got: {rule['noDataState']}",
        )
    except Exception as exc:
        record(f"  Proxmox Node Down ({PROXMOX_NODE_DOWN_UID}) accessible", False, str(exc))

    # ── Prometheus Target Down ────────────────────────────────────────────────
    print("\n  [B] Prometheus Target Down (pve job excluded)")
    try:
        rule = await client.get(f"v1/provisioning/alert-rules/{TARGET_DOWN_UID}")
        record("  Prometheus Target Down exists", True)

        expr = _get_pve_expr(rule) or ""
        record(
            "  query excludes pve job (up{job!=\"pve\"} == 0)",
            "job!=" in expr or 'job!="pve"' in expr,
            f"expr: {expr}",
        )
        record(
            "  execErrState=KeepLast",
            rule["execErrState"] == "KeepLast",
            f"got: {rule['execErrState']}",
        )
    except Exception as exc:
        record(f"  Prometheus Target Down ({TARGET_DOWN_UID}) accessible", False, str(exc))

    # ── pve_exporter Unreachable (new) ────────────────────────────────────────
    print("\n  [C] pve_exporter Unreachable (new dedicated alert)")
    try:
        rule = await client.get(f"v1/provisioning/alert-rules/{PVE_EXPORTER_UID}")
        record("  pve_exporter Unreachable exists", True)

        expr = _get_pve_expr(rule) or ""
        record(
            "  queries up{job=\"pve\"} (pve_exporter scrape status)",
            'job="pve"' in expr,
            f"expr: {expr}",
        )
        record(
            "  noDataState=OK (no alarm when exporter just started)",
            rule["noDataState"] == "OK",
            f"got: {rule['noDataState']}",
        )
        record(
            "  execErrState=KeepLast",
            rule["execErrState"] == "KeepLast",
            f"got: {rule['execErrState']}",
        )
        record(
            "  severity=warning (connectivity issue, not node outage)",
            rule.get("labels", {}).get("severity") == "warning",
            f"got: {rule.get('labels', {}).get('severity')}",
        )
        record(
            "  for=5m (requires 5 consecutive failures before alerting)",
            rule["for"] == "5m",
            f"got: {rule['for']}",
        )
    except Exception as exc:
        record(f"  pve_exporter Unreachable ({PVE_EXPORTER_UID}) exists", False, str(exc))

    # ── Notification policy ───────────────────────────────────────────────────
    print("\n  [D] Notification policy routes to Discord")
    try:
        policy = await client.get("v1/provisioning/policies")
        receiver = policy.get("receiver", "")
        record(
            "  Default receiver is Discord",
            "discord" in receiver.lower() or receiver == "Discord",
            f"receiver='{receiver}'",
        )
    except Exception as exc:
        record("  Notification policy accessible", False, str(exc))


# ─── verify phase ─────────────────────────────────────────────────────────────

async def test_verify_phase(client: GrafanaClient) -> None:
    """Full verification — all expected rules exist with correct settings."""
    await test_after_phase(client)

    # Also verify alert rule groups load cleanly
    print("\n  [E] All Proxmox alert rules in group are loadable")
    try:
        all_rules = await client.get("v1/provisioning/alert-rules")
        proxmox_rules = [r for r in all_rules if r.get("ruleGroup") == "Proxmox"]
        record(f"  Proxmox rule group has rules", len(proxmox_rules) > 0, f"count={len(proxmox_rules)}")

        expected_uids = {PROXMOX_NODE_DOWN_UID, PVE_EXPORTER_UID}
        found_uids = {r["uid"] for r in proxmox_rules}
        missing = expected_uids - found_uids
        record(
            "  All expected Proxmox UIDs present",
            len(missing) == 0,
            f"missing={missing}" if missing else f"found={found_uids}",
        )
    except Exception as exc:
        record("  All alert rules loadable", False, str(exc))


# ─── summary ──────────────────────────────────────────────────────────────────

def print_summary() -> int:
    passed = sum(1 for r in results if r["passed"])
    total  = len(results)
    failed = total - passed
    pct    = int(passed / total * 100) if total else 0

    print(f"\n{'═'*55}")
    print(f"  Results: {passed}/{total} passed ({pct}%)")
    if failed:
        print(f"\n  Failed tests:")
        for r in results:
            if not r["passed"]:
                print(f"    ❌  {r['name']}" + (f"  [{r['detail']}]" if r["detail"] else ""))
    print(f"{'═'*55}\n")
    return 1 if failed else 0


# ─── main ─────────────────────────────────────────────────────────────────────

async def main(phase: str) -> int:
    client = GrafanaClient()

    print(f"\n{'─'*55}")
    print(f"  Proxmox Alert Improvements — Test Suite ({phase.upper()})")
    print(f"{'─'*55}")

    if phase == "before":
        await test_before_phase(client)
    elif phase == "after":
        await test_after_phase(client)
    elif phase == "verify":
        await test_verify_phase(client)
    else:
        print(f"Unknown phase: {phase!r}. Use --phase before|after|verify")
        return 1

    return print_summary()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Proxmox alert rule improvements")
    parser.add_argument(
        "--phase",
        choices=["before", "after", "verify"],
        default="verify",
        help="Test phase: before (baseline), after (post-fix), or verify (full check)",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.phase)))
