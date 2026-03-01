#!/usr/bin/env python3
"""
Infrastructure Monitoring — Frontend Test Suite
================================================
Validates all Grafana dashboards by:
  1. Verifying dashboards exist with correct versions
  2. Executing every PromQL query in each dashboard panel
  3. Classifying results: live data / known-pending / parse error / empty
  4. Testing alert rule states and notification channels
  5. Reporting per-dashboard pass rates

Usage:
    python frontend_test.py              # full suite
    python frontend_test.py --dashboard lcHlCU2Vz   # single dashboard
    python frontend_test.py --alerts-only
"""
import os
import sys
import re
import json
import argparse
import urllib.request
import urllib.parse
import urllib.error
import ssl
import datetime
from typing import Any

# ── Config ───────────────────────────────────────────────────────────────────
# Set GRAFANA_TOKEN env var before running: export GRAFANA_TOKEN=glsa_...
GRAFANA       = "https://grafana.local.defaultvaluation.com"
GRAFANA_TOKEN = os.environ.get("GRAFANA_TOKEN", "")
PROM_DS_UID   = "ceb67eiok1qf4d"

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# ── Colours ──────────────────────────────────────────────────────────────────
GR = "\033[92m"; RE = "\033[91m"; YE = "\033[93m"; CY = "\033[96m"
BO = "\033[1m";  RS = "\033[0m"
OK = f"{GR}✅{RS}"; KO = f"{RE}❌{RS}"; WA = f"{YE}⚠️ {RS}"; IN = f"{CY}ℹ️ {RS}"

results: list[dict] = []

def record(category: str, name: str, passed: bool, detail: str = ""):
    results.append({"category": category, "name": name, "passed": passed, "detail": detail})
    icon = OK if passed else KO
    det  = f"  {YE}{detail}{RS}" if detail and not passed else (f"  {detail}" if detail else "")
    print(f"  {icon}  {name}{det}")


# ── HTTP ─────────────────────────────────────────────────────────────────────
def _get(url: str, headers: dict | None = None, timeout: int = 15) -> tuple[int, Any]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=timeout) as r:
            raw = r.read().decode()
            try:    return r.status, json.loads(raw)
            except: return r.status, raw
    except urllib.error.HTTPError as e:
        try:    return e.code, json.loads(e.read().decode())
        except: return e.code, {}
    except Exception as e:
        return 0, str(e)

def gapi(path: str) -> tuple[int, Any]:
    return _get(f"{GRAFANA}{path}", {"Authorization": f"Bearer {GRAFANA_TOKEN}"})

def prom(expr: str) -> tuple[bool, list, str]:
    enc = urllib.parse.quote(expr)
    status, data = gapi(f"/api/datasources/proxy/uid/{PROM_DS_UID}/api/v1/query?query={enc}")
    if status == 0:   return False, [], str(data)
    if not isinstance(data, dict): return False, [], f"HTTP {status}: {str(data)[:80]}"
    if data.get("status") == "success":
        r = data.get("data", {}).get("result", [])
        return len(r) > 0, r, ""
    return False, [], data.get("error", "unknown")


# ── Dashboard inventory ───────────────────────────────────────────────────────
DASHBOARDS = {
    "lcHlCU2Vz": {
        "name": "Synology NAS — Full System Overview",
        "min_version": 4,
        "panels": [
            # Stat panels
            ("CPU Usage %",       '(1 - avg(rate(node_cpu_seconds_total{mode="idle",job="node_exporter"}[2m]))) * 100', True),
            ("RAM Usage %",       '(1 - node_memory_MemAvailable_bytes{job="node_exporter"} / node_memory_MemTotal_bytes{job="node_exporter"}) * 100', True),
            ("Load 1m",           'node_load1{job="node_exporter"}', True),
            ("Load 5m",           'node_load5{job="node_exporter"}', True),
            ("Load 15m",          'node_load15{job="node_exporter"}', True),
            ("Uptime",            'node_time_seconds{job="node_exporter"} - node_boot_time_seconds{job="node_exporter"}', True),
            ("RAM Total",         'node_memory_MemTotal_bytes{job="node_exporter"}', True),
            ("CPU Temperature",   'node_hwmon_temp_celsius{job="node_exporter"}', True),
            ("RAM Available",     'node_memory_MemAvailable_bytes{job="node_exporter"}', True),
            ("Disk Used %",       'container_fs_usage_bytes{job="cadvisor",id="/",device="/dev/mapper/cachedev_0"} / container_fs_limit_bytes{job="cadvisor",id="/",device="/dev/mapper/cachedev_0"} * 100', True),
            ("Disk Free",         'container_fs_limit_bytes{job="cadvisor",id="/",device="/dev/mapper/cachedev_0"} - container_fs_usage_bytes{job="cadvisor",id="/",device="/dev/mapper/cachedev_0"}', True),
            ("UniFi Devices",     'unpoller_site_aps{job="unifi"}', True),
            # Time series
            ("CPU by Mode",       '(1 - avg(rate(node_cpu_seconds_total{mode="idle",job="node_exporter"}[2m]))) * 100', True),
            ("Memory Breakdown",  'node_memory_MemTotal_bytes{job="node_exporter"} - node_memory_MemAvailable_bytes{job="node_exporter"}', True),
            ("Disk Throughput",   'sum(irate(node_disk_read_bytes_total{job="node_exporter"}[2m]))', True),
            ("Disk IOPS",         'sum(irate(node_disk_reads_completed_total{job="node_exporter"}[2m]))', True),
            ("Net Traffic",       'sum(irate(container_network_receive_bytes_total{job="cadvisor",id="/",interface=~"eth.*|tailscale.*"}[2m]))', True),
            ("Load Trend",        'node_load15{job="node_exporter"}', True),
            # UniFi section
            ("UniFi Total Dev",   'count(unpoller_device_info{job="unifi"})', True),
            ("UniFi APs",         'unpoller_site_aps{job="unifi"}', True),
            ("UniFi Clients",     'unpoller_site_stations{job="unifi"}', True),
            ("UniFi Switches",    'unpoller_site_switches{job="unifi"}', True),
            ("WAN DL",            'sum(unpoller_site_xput_down_rate{job="unifi"})', True),
            ("WAN UL",            'sum(unpoller_site_xput_up_rate{job="unifi"})', True),
            ("WAN Latency",       'unpoller_site_latency_seconds{job="unifi"} * 1000', True),
            ("UniFi Uptime",      'unpoller_controller_uptime_seconds{job="unifi"}', True),
            ("Site Throughput",   'sum(irate(unpoller_site_receive_rate_bytes{job="unifi"}[5m]))', True),
            ("WiFi Clients TS",   'unpoller_site_stations{job="unifi"}', True),
            # Speedtest (long interval — may be pending)
            ("Speedtest DL avg",  'avg(avg_over_time(speedtest_download_speed_Bps[1w:5m]))', False),
            ("Speedtest UL avg",  'avg(avg_over_time(speedtest_upload_speed_Bps[1w:5m]))', False),
            ("Speedtest Lat avg", 'avg(avg_over_time(speedtest_latency_seconds[1w:5m])) * 1000', False),
            # SNMP section (pending prometheus.yml reload)
            ("SNMP System Status",'systemStatus{job="snmp",instance="synology-nas"}', False),
            ("SNMP Disk Temp",    'diskTemperature{job="snmp",instance="synology-nas"}', False),
            ("SNMP RAID Used",    '(raidTotalSize{job="snmp",instance="synology-nas"} - raidFreeSize{job="snmp",instance="synology-nas"}) / raidTotalSize{job="snmp",instance="synology-nas"} * 100', False),
        ],
    },
    "portainer-overview-v1": {
        "name": "Portainer — Docker Host & Container Overview",
        "min_version": 4,
        "panels": [
            ("CPU cores",         'count(node_cpu_seconds_total{mode="idle",job="node_exporter"})', True),
            ("RAM Total",         'node_memory_MemTotal_bytes{job="node_exporter"}', True),
            ("System Uptime",     'node_time_seconds{job="node_exporter"} - node_boot_time_seconds{job="node_exporter"}', True),
            ("Load 1m",           'node_load1{job="node_exporter"}', True),
            ("Disk Free (main)",  'container_fs_limit_bytes{job="cadvisor",id="/",device="/dev/mapper/cachedev_0"} - container_fs_usage_bytes{job="cadvisor",id="/",device="/dev/mapper/cachedev_0"}', True),
            ("Root cgroup RAM",   'container_memory_usage_bytes{job="cadvisor",id="/"}', True),
            ("Root cgroup CPU",   'sum(container_cpu_usage_seconds_total{job="cadvisor",id="/"})', True),
            ("Machine memory",    'machine_memory_bytes{job="cadvisor"}', True),
            ("CPU usage TS",      '(1 - avg(rate(node_cpu_seconds_total{mode="idle",job="node_exporter"}[2m]))) * 100', True),
            ("Memory TS",         'node_memory_MemAvailable_bytes{job="node_exporter"}', True),
            ("Net RX (cAdvisor)", 'sum(irate(container_network_receive_bytes_total{job="cadvisor",id="/",interface=~"eth.*|tailscale.*"}[2m]))', True),
            ("Disk IO",           'sum(irate(node_disk_read_bytes_total{job="node_exporter"}[2m]))', True),
        ],
    },
    "proxmox-bab1-v2": {
        "name": "Proxmox — bab1 Cluster",
        "min_version": 3,
        "panels": [
            ("pve_up",            'pve_up{job="pve"}', False),
            ("Proxmox CPU",       'pve_cpu_usage_ratio{job="pve",type="node"}', False),
            ("Proxmox RAM used",  'pve_memory_usage_bytes{job="pve",type="node"}', False),
            ("Proxmox RAM total", 'pve_memory_size_bytes{job="pve",type="node"}', False),
            ("Proxmox disk",      'pve_disk_usage_bytes{job="pve",type="node"}', False),
            ("VM count",          'count(pve_up{job="pve",type="qemu"})', False),
            ("LXC count",         'count(pve_up{job="pve",type="lxc"})', False),
        ],
    },
}

# Panels where no data is EXPECTED right now (known infrastructure gaps)
KNOWN_PENDING = {
    # pve_exporter: volume typo → fix /etc/pvc.yml → /etc/pve.yml in Portainer
    "pve_up", "Proxmox CPU", "Proxmox RAM used", "Proxmox RAM total",
    "Proxmox disk", "VM count", "LXC count",
    # SNMP: synology module missing from snmp.yml → deploy new snmp.yml
    "SNMP System Status", "SNMP Disk Temp", "SNMP RAID Used",
    # Speedtest: 60 min interval, may not have run recently
    "Speedtest DL avg", "Speedtest UL avg", "Speedtest Lat avg",
}


# ── 1. Dashboard existence & version check ───────────────────────────────────
def test_dashboard_existence():
    print(f"\n{BO}{CY}━━ 1. Dashboard Existence & Version ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RS}")
    dashboard_data = {}
    for uid, cfg in DASHBOARDS.items():
        status, data = gapi(f"/api/dashboards/uid/{uid}")
        ok = status == 200
        if ok:
            dash = data.get("dashboard", {})
            ver  = dash.get("version", 0)
            title = dash.get("title", "?")
            ver_ok = ver >= cfg["min_version"]
            record("existence", f"[{uid}] {cfg['name']}", ver_ok,
                   f"v{ver} (min: {cfg['min_version']}) | '{title}'")
            dashboard_data[uid] = dash
        else:
            record("existence", f"[{uid}] {cfg['name']}", False, f"HTTP {status} — dashboard not found")
    return dashboard_data


# ── 2. Panel PromQL execution ────────────────────────────────────────────────
def test_dashboard_panels(uid_filter: str | None = None):
    print(f"\n{BO}{CY}━━ 2. Dashboard Panel PromQL Tests ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RS}")
    total_panels = total_live = total_pending = total_fail = 0

    for uid, cfg in DASHBOARDS.items():
        if uid_filter and uid != uid_filter:
            continue
        print(f"\n  {BO}  {cfg['name']} [{uid}]{RS}")
        dash_pass = dash_pend = dash_fail = 0

        for panel_name, expr, required in cfg["panels"]:
            has_data, res, err = prom(expr)
            total_panels += 1
            is_pending = panel_name in KNOWN_PENDING

            if has_data:
                record("panels", f"    {uid} → {panel_name}", True, f"{len(res)} series")
                total_live += 1
                dash_pass  += 1
            elif is_pending:
                record("panels", f"    {uid} → {panel_name}", True, "no data (known pending fix)")
                total_pending += 1
                dash_pend += 1
            elif "parse error" in err.lower():
                record("panels", f"    {uid} → {panel_name}", False, f"PARSE ERROR: {err[:80]}")
                total_fail += 1
                dash_fail  += 1
            elif not required:
                record("panels", f"    {uid} → {panel_name}", True, "no data (non-required, long interval)")
                total_pending += 1
                dash_pend += 1
            else:
                record("panels", f"    {uid} → {panel_name}", False, f"no data — {err or 'empty result'}")
                total_fail += 1
                dash_fail  += 1

        pct = int(100 * (dash_pass + dash_pend) / (dash_pass + dash_pend + dash_fail)) if (dash_pass + dash_pend + dash_fail) else 0
        sym = OK if dash_fail == 0 else (WA if pct >= 80 else KO)
        print(f"\n    {sym}  Panel score: {dash_pass} live | {dash_pend} pending | {dash_fail} failing ({pct}%)\n")

    return total_panels, total_live, total_pending, total_fail


# ── 3. Alert rules & state ────────────────────────────────────────────────────
PRODUCTION_RULES = {
    "NAS Host Memory Critical",
    "NAS Host Memory High",
    "NAS System Load High",
    "NAS Temperature High",
    "NAS Host CPU Usage High",
    "Prometheus Target Down",
    "UniFi WAN Latency High",
    "UniFi Device Firmware Update Available",
    "Proxmox Node Down",
    "Proxmox Node Memory High",
    "Proxmox Storage Critical",
}

EXPECTED_FIRING = {
    # "Prometheus Target Down" fires because pve target is DOWN — expected until fix applied
    "Prometheus Target Down",
}

def test_alerts():
    print(f"\n{BO}{CY}━━ 3. Alert Rules & State ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RS}")

    # Check all rules exist
    status, groups = gapi("/api/ruler/grafana/api/v1/rules")
    if status != 200:
        record("alerts", "Alert ruler API", False, f"HTTP {status}")
        return

    all_rules: list[str] = []
    for folder, group_list in (groups if isinstance(groups, dict) else {}).items():
        for grp in group_list:
            for rule in grp.get("rules", []):
                title = rule.get("grafana_alert", {}).get("title", rule.get("alert", "?"))
                all_rules.append(title)

    missing = PRODUCTION_RULES - set(all_rules)
    test_rules = [r for r in all_rules if r not in PRODUCTION_RULES]

    record("alerts", f"All production rules present ({len(PRODUCTION_RULES)} expected)",
           len(missing) == 0,
           f"Missing: {', '.join(missing)}" if missing else f"{len(all_rules)} total ({len(test_rules)} test rules)")

    for rule_name in PRODUCTION_RULES:
        record("alerts", f"  Rule exists: {rule_name}", rule_name in all_rules,
               "NOT FOUND" if rule_name not in all_rules else "")

    # Check evaluation state
    status2, state_data = gapi("/api/prometheus/grafana/api/v1/rules")
    if status2 != 200:
        record("alerts", "Alert state API", False, f"HTTP {status2}")
        return

    firing: list[str] = []
    inactive: list[str] = []
    for grp in state_data.get("data", {}).get("groups", []):
        for rule in grp.get("rules", []):
            name  = rule.get("name", "")
            state = rule.get("state", "")
            if state == "firing":
                firing.append(name)
            else:
                inactive.append(name)

    unexpected_fire = [r for r in firing if r not in EXPECTED_FIRING and "test" not in r.lower()]
    expected_fire   = [r for r in firing if r in EXPECTED_FIRING]

    record("alerts", "No unexpected alerts firing", len(unexpected_fire) == 0,
           f"Unexpected firing: {', '.join(unexpected_fire)}" if unexpected_fire else
           (f"Expected firing (known): {', '.join(expected_fire)}" if expected_fire else "all clear"))

    print(f"\n  {IN} Firing: {firing or ['none']}  |  Inactive/normal: {len(inactive)}")
    if test_rules:
        print(f"  {IN} Test rules (to delete after pve fix): {test_rules}")


# ── 4. Contact points / notification channels ────────────────────────────────
def test_notifications():
    print(f"\n{BO}{CY}━━ 4. Notification Channels ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RS}")
    status, contacts = gapi("/api/v1/provisioning/contact-points")
    if status != 200:
        record("notifications", "Contact points API", False, f"HTTP {status}")
        return

    record("notifications", "Contact points API accessible", True, f"{len(contacts)} channel(s)")
    for cp in contacts:
        name   = cp.get("name", "?")
        ctype  = cp.get("type", "?")
        record("notifications", f"  Channel: {name} [{ctype}]", True, "")

    # Check alert notification policy
    status2, policy = gapi("/api/v1/provisioning/policies")
    ok = status2 == 200 and isinstance(policy, dict)
    record("notifications", "Alert routing policy configured",
           ok and bool(policy.get("receiver", "")),
           policy.get("receiver", "?") if ok else f"HTTP {status2}")


# ── 5. Grafana system health ──────────────────────────────────────────────────
def test_grafana_health():
    print(f"\n{BO}{CY}━━ 5. Grafana System Health ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RS}")

    # Prometheus datasource
    status, data = gapi(f"/api/datasources/uid/{PROM_DS_UID}/health")
    ok = status == 200 and isinstance(data, dict) and data.get("status") == "OK"
    record("health", "Prometheus datasource healthy", ok,
           data.get("message", "") if isinstance(data, dict) else f"HTTP {status}")

    # Grafana version
    status2, metadata = gapi("/api/health")
    record("health", "Grafana API reachable", status2 in (200, 401),
           metadata.get("version", "?") if isinstance(metadata, dict) else f"HTTP {status2}")

    # Total dashboards
    status3, dash_list = gapi("/api/search?type=dash-db")
    if status3 == 200 and isinstance(dash_list, list):
        record("health", "Dashboard count", True, f"{len(dash_list)} dashboards in Grafana")
        infra_dashboards = [d for d in dash_list if "Infrastructure" in (d.get("folderTitle", "")
                                                                          or d.get("folderTitle", ""))]
        if infra_dashboards:
            print(f"\n  {IN} Infrastructure folder dashboards:")
            for d in infra_dashboards:
                print(f"    • [{d.get('uid','?')}] {d.get('title','?')} (v{d.get('version','?')})")


# ── Summary ───────────────────────────────────────────────────────────────────
def print_summary(panel_stats: tuple | None = None):
    print(f"\n{BO}{'━'*70}{RS}")
    print(f"{BO}  FRONTEND TEST SUMMARY — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RS}")
    print(f"{'━'*70}")

    by_cat: dict[str, list] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r)

    total_pass = total_fail = 0
    for cat, cat_results in by_cat.items():
        passed = sum(1 for r in cat_results if r["passed"])
        failed = len(cat_results) - passed
        total_pass += passed
        total_fail += failed
        icon = OK if failed == 0 else (WA if passed > 0 else KO)
        print(f"  {icon}  {cat.upper():<22} {passed}/{len(cat_results)} passed")

    if panel_stats:
        n, live, pend, fail = panel_stats
        print(f"\n  {IN} Panel breakdown: {live} live data | {pend} pending fixes | {fail} failing | {n} total")

    print(f"{'━'*70}")
    pct = int(100 * total_pass / (total_pass + total_fail)) if (total_pass + total_fail) else 0
    icon = OK if total_fail == 0 else (WA if pct >= 80 else KO)
    print(f"\n  {icon}  OVERALL: {total_pass}/{total_pass + total_fail} passed ({pct}%)")

    # Failures
    failures = [r for r in results if not r["passed"]]
    if failures:
        print(f"\n{BO}  Failed tests:{RS}")
        for r in failures:
            d = re.sub(r'\x1b\[[0-9;]*m', '', r["detail"])
            print(f"    {KO}  [{r['category']}] {r['name']} — {d}")

    # Action items
    print(f"\n{BO}  Required actions to reach 100%:{RS}")
    print(f"  1. Portainer → monitoring stack → pve-exporter service:")
    print(f"     Change:  /volume1/docker/grafana/pve.yml:/etc/pvc.yml:ro")
    print(f"     To:      /volume1/docker/grafana/pve.yml:/etc/pve.yml:ro")
    print(f"     (one char: pvc → pve) then redeploy")
    print(f"  2. Copy infra-monitoring/snmp/synology-snmp.yml → /volume1/docker/grafana/snmp.yml")
    print(f"     then: docker restart SNMP_Exporter")
    print(f"     ↳ Fixes: SNMP disk temp, RAID status, system health panels")
    print(f"  3. After pve data flows: delete test rules pve-test-{{cpu,mem,uptime}}-firing\n")
    print(f"{'━'*70}\n")

    return 0 if total_fail == 0 else 1


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Infrastructure monitoring frontend test suite")
    parser.add_argument("--dashboard", help="Test a single dashboard UID")
    parser.add_argument("--alerts-only", action="store_true")
    args = parser.parse_args()

    print(f"\n{BO}{'━'*70}")
    print(f"  Infrastructure Monitoring — Frontend Test Suite")
    print(f"  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'━'*70}{RS}")
    print(f"  Grafana: {GRAFANA}")

    panel_stats = None

    if not args.alerts_only:
        test_dashboard_existence()
        panel_stats = test_dashboard_panels(uid_filter=args.dashboard)

    test_alerts()
    test_notifications()
    test_grafana_health()

    sys.exit(print_summary(panel_stats))


if __name__ == "__main__":
    main()
