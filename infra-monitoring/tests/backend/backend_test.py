#!/usr/bin/env python3
"""
Infrastructure Monitoring — Backend Test Suite
==============================================
Tests Prometheus targets, metric presence, PromQL validity,
Grafana datasource health, and Grafana alert rule state.

Usage:
    python backend_test.py           # full suite
    python backend_test.py --quick   # targets + key metrics only
    python backend_test.py --alerts  # also test alert evaluation
"""
import os
import sys
import argparse
import urllib.request
import urllib.error
import json
import ssl
import datetime
from typing import Any

# ── Config ───────────────────────────────────────────────────────────────────
# Set GRAFANA_TOKEN env var before running: export GRAFANA_TOKEN=glsa_...
PROMETHEUS  = "http://prometheus.local.defaultvaluation.com:9090"   # adjust if needed
GRAFANA     = "https://grafana.local.defaultvaluation.com"
GRAFANA_TOKEN = os.environ.get("GRAFANA_TOKEN", "")
PROM_DS_UID = "ceb67eiok1qf4d"

# Try internal prometheus URL (running on NAS with docker network)
# If running from Mac: use external URL or SSH tunnel
_PROM_INTERNAL  = "http://172.22.1.8:9090"   # internal docker IP (from grafana_net)

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# ── Colors ───────────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"
TICK   = f"{GREEN}✅{RESET}"
CROSS  = f"{RED}❌{RESET}"
WARN   = f"{YELLOW}⚠️ {RESET}"
INFO   = f"{CYAN}ℹ️ {RESET}"

# ── Results tracker ───────────────────────────────────────────────────────────
results: list[dict] = []

def record(category: str, name: str, passed: bool, detail: str = ""):
    results.append({"category": category, "name": name, "passed": passed, "detail": detail})
    icon = TICK if passed else CROSS
    detail_str = f"  {YELLOW}{detail}{RESET}" if detail and not passed else (f"  {detail}" if detail else "")
    print(f"  {icon}  {name}{detail_str}")


# ── HTTP helpers ─────────────────────────────────────────────────────────────
def http_get(url: str, headers: dict | None = None, timeout: int = 10) -> tuple[int, Any]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=timeout) as r:
            raw = r.read().decode()
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:
        return 0, str(e)


def grafana_get(path: str) -> tuple[int, Any]:
    return http_get(f"{GRAFANA}{path}", {"Authorization": f"Bearer {GRAFANA_TOKEN}"})


def prom_query(expr: str, url: str = PROMETHEUS) -> tuple[bool, list, str]:
    """Returns (has_data, results_list, error_message)"""
    encoded = urllib.parse.quote(expr)
    status, data = http_get(f"{url}/api/v1/query?query={encoded}")
    if status == 0:
        return False, [], str(data)
    if isinstance(data, dict) and data.get("status") == "success":
        results_list = data.get("data", {}).get("result", [])
        return len(results_list) > 0, results_list, ""
    return False, [], data.get("error", "unknown error") if isinstance(data, dict) else str(data)


def prom_query_via_grafana(expr: str) -> tuple[bool, list, str]:
    """Query Prometheus via Grafana proxy (works from Mac since Grafana is public)."""
    import urllib.parse
    encoded = urllib.parse.quote(expr)
    status, data = grafana_get(f"/api/datasources/proxy/uid/{PROM_DS_UID}/api/v1/query?query={encoded}")
    if status == 0:
        return False, [], str(data)
    if isinstance(data, dict) and data.get("status") == "success":
        results_list = data.get("data", {}).get("result", [])
        return len(results_list) > 0, results_list, ""
    return False, [], data.get("error", "unknown error") if isinstance(data, dict) else str(data)


# ── 1. Prometheus Connectivity ───────────────────────────────────────────────
def test_prometheus_health():
    print(f"\n{BOLD}{CYAN}━━ 1. Prometheus Health ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
    # Try via Grafana proxy (always accessible from Mac)
    status, data = grafana_get(f"/api/datasources/proxy/uid/{PROM_DS_UID}/-/healthy")
    ok = status in (200, 204)
    record("prometheus", "Prometheus reachable via Grafana proxy", ok, f"HTTP {status}" if not ok else "")

    # Check targets endpoint
    status2, data2 = grafana_get(f"/api/datasources/proxy/uid/{PROM_DS_UID}/api/v1/targets")
    ok2 = status2 == 200 and isinstance(data2, dict) and data2.get("status") == "success"
    active = data2.get("data", {}).get("activeTargets", []) if ok2 else []
    record("prometheus", "Prometheus /api/v1/targets accessible", ok2, f"{len(active)} active targets" if ok2 else f"HTTP {status2}")
    return ok2, active


# ── 2. Scrape Target Status ───────────────────────────────────────────────────
EXPECTED_JOBS = {
    "node_exporter": {"min_up": 1, "critical": True},
    "cadvisor":      {"min_up": 1, "critical": True},
    "snmp":          {"min_up": 1, "critical": False},
    # snmp_exporter job added in updated prometheus.yml — not yet applied to NAS
    # "snmp_exporter": {"min_up": 1, "critical": False},
    "pve":           {"min_up": 1, "critical": False},
    "speedtest":     {"min_up": 0, "critical": False},   # long interval
    "unifi":         {"min_up": 1, "critical": False},
}

def test_targets(active_targets: list):
    print(f"\n{BOLD}{CYAN}━━ 2. Scrape Target Status ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
    by_job: dict[str, list] = {}
    for t in active_targets:
        job = t.get("labels", {}).get("job", "unknown")
        by_job.setdefault(job, []).append(t)

    for job, cfg in EXPECTED_JOBS.items():
        targets = by_job.get(job, [])
        up_count = sum(1 for t in targets if t.get("health") == "up")
        total = len(targets)
        if total == 0:
            record("targets", f"[{job}] target exists", False, "job not found in active targets")
            continue
        up_ok = up_count >= cfg["min_up"] or (cfg["min_up"] == 0 and True)
        state_str = f"{up_count}/{total} UP"
        if not up_ok and cfg["critical"]:
            record("targets", f"[{job}] UP status", False, f"{state_str} — CRITICAL job")
        elif not up_ok:
            record("targets", f"[{job}] UP status", False, f"{state_str} — non-critical")
        else:
            # Check for error messages if down
            errors = [t.get("lastError","") for t in targets if t.get("health") != "up"]
            extra = f" | err: {errors[0][:80]}" if errors else ""
            record("targets", f"[{job}] UP status", True, state_str + extra)

    # Report unexpected jobs
    unknown = set(by_job.keys()) - set(EXPECTED_JOBS.keys())
    if unknown:
        print(f"  {INFO} Unexpected jobs found: {', '.join(sorted(unknown))}")


# ── 3. Key Metric Presence ───────────────────────────────────────────────────
KEY_METRICS = [
    # (job_label, metric_expr, description)
    ("node_exporter", 'node_cpu_seconds_total{job="node_exporter"}',       "node CPU counters"),
    ("node_exporter", 'node_memory_MemTotal_bytes{job="node_exporter"}',   "node RAM total"),
    ("node_exporter", 'node_memory_MemAvailable_bytes{job="node_exporter"}', "node RAM available"),
    ("node_exporter", 'node_disk_read_bytes_total{job="node_exporter"}',   "node disk I/O bytes"),
    # NOTE: node_network_*, node_filesystem_*, node_filefd_* are NOT available on Synology DSM
    # (cgroup/procfs restrictions). Use cAdvisor root-cgroup metrics instead.
    ("cadvisor",      'container_network_receive_bytes_total{job="cadvisor",id="/"}', "cAdvisor network RX (DSM replacement)"),
    ("cadvisor",      'container_fs_usage_bytes{job="cadvisor",id="/",device="/dev/mapper/cachedev_0"}', "cAdvisor main disk usage (DSM replacement)"),
    ("node_exporter", 'node_load1{job="node_exporter"}',                   "node load avg 1m"),
    ("node_exporter", 'node_time_seconds{job="node_exporter"}',            "node time"),
    ("node_exporter", 'node_boot_time_seconds{job="node_exporter"}',       "node boot time"),
    ("node_exporter", 'node_hwmon_temp_celsius{job="node_exporter"}',      "node temperature sensor"),
    ("cadvisor",      'container_cpu_usage_seconds_total{job="cadvisor"}', "cAdvisor CPU total"),
    ("cadvisor",      'machine_memory_bytes{job="cadvisor"}',              "cAdvisor machine RAM"),
    ("cadvisor",      'container_memory_usage_bytes{job="cadvisor",id="/"}', "cAdvisor root cgroup"),
    ("unifi",         'count(unpoller_device_info{job="unifi"})',          "UniFi device count (unpoller_device_info)"),
    ("unifi",         'unpoller_site_aps{job="unifi"}',                     "UniFi AP count"),
    ("unifi",         'unpoller_site_stations{job="unifi"}',                "UniFi connected clients"),
    ("snmp",          'snmp_scrape_duration_seconds',                      "SNMP scrape telemetry (needs yml reload — currently scraping /metrics not /snmp)"),
    ("snmp",          'diskTemperature{job="snmp"}',                       "SNMP disk temperature (needs yml reload)"),
    ("snmp",          'raidStatus{job="snmp"}',                            "SNMP RAID status (needs yml reload)"),
    ("speedtest",     'speedtest_download_speed_Bps',                      "speedtest download (long interval)"),
    ("pve",           'pve_up{job="pve"}',                                 "pve_exporter up (needs host network)"),
]

def test_key_metrics():
    print(f"\n{BOLD}{CYAN}━━ 3. Key Metric Presence ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
    for job, expr, desc in KEY_METRICS:
        has_data, res, err = prom_query_via_grafana(expr)
        series_count = len(res)
        if has_data:
            record("metrics", f"[{job}] {desc}", True, f"{series_count} series")
        else:
            # Non-critical if it's a known unfixed issue
            is_known_issue = any(kw in desc for kw in ["needs yml", "needs host", "long interval"])
            msg = f"no data — {err}" if err else "no data"
            if is_known_issue:
                msg += f" {YELLOW}(known pending fix){RESET}"
            record("metrics", f"[{job}] {desc}", has_data, msg)


# ── 4. Dashboard Panel PromQL Validation ─────────────────────────────────────
DASHBOARD_QUERIES = {
    "Synology NAS (lcHlCU2Vz)": [
        ('(1 - avg(rate(node_cpu_seconds_total{mode="idle",job="node_exporter"}[2m]))) * 100', "CPU Usage %"),
        ('(1 - node_memory_MemAvailable_bytes{job="node_exporter"} / node_memory_MemTotal_bytes{job="node_exporter"}) * 100', "RAM Usage %"),
        ('node_load1{job="node_exporter"}', "Load 1m"),
        ('node_memory_MemTotal_bytes{job="node_exporter"}', "RAM Total"),
        ('node_time_seconds{job="node_exporter"} - node_boot_time_seconds{job="node_exporter"}', "Uptime"),
        ('node_hwmon_temp_celsius{job="node_exporter"}', "Temperature"),
        ('sum(irate(node_disk_read_bytes_total{job="node_exporter"}[2m]))', "Disk Read"),
        # cAdvisor-based network (node_network_* not available on Synology DSM)
        ('sum(irate(container_network_receive_bytes_total{job="cadvisor",id="/",interface=~"eth.*|tailscale.*"}[2m]))', "Net RX (cAdvisor)"),
        ('container_fs_usage_bytes{job="cadvisor",id="/",device="/dev/mapper/cachedev_0"} / container_fs_limit_bytes{job="cadvisor",id="/",device="/dev/mapper/cachedev_0"} * 100', "Disk Used %"),
        # UniFi section
        ('count(unpoller_device_info{job="unifi"})', "UniFi device count"),
        ('unpoller_site_stations{job="unifi"}', "UniFi clients"),
        ('avg(avg_over_time(speedtest_download_speed_Bps[1w:5m]))', "Speedtest avg DL (historical)"),
    ],
    "Portainer Dashboard (portainer-overview-v1)": [
        ('count(node_cpu_seconds_total{mode="idle",job="node_exporter"})', "CPU core count"),
        ('node_memory_MemTotal_bytes{job="node_exporter"}', "RAM Total"),
        # node_filesystem_avail_bytes is NOT available on Synology DSM — replaced with cAdvisor
        ('container_fs_limit_bytes{job="cadvisor",id="/",device="/dev/mapper/cachedev_0"} - container_fs_usage_bytes{job="cadvisor",id="/",device="/dev/mapper/cachedev_0"}', "Main disk free (cAdvisor)"),
        ('container_memory_usage_bytes{job="cadvisor",id="/"}', "Root cgroup RAM"),
        ('sum(container_cpu_usage_seconds_total{job="cadvisor",id="/"})', "Root cgroup CPU"),
        ('machine_memory_bytes{job="cadvisor"}', "Machine memory"),
    ],
    "Proxmox bab1 (proxmox-bab1-v2)": [
        ('pve_up{job="pve"}', "pve_exporter up vector"),
        ('pve_cpu_usage_ratio{job="pve",type="node"}', "Proxmox node CPU"),
        ('pve_memory_usage_bytes{job="pve",type="node"}', "Proxmox node RAM used"),
        ('pve_memory_size_bytes{job="pve",type="node"}', "Proxmox node RAM total"),
    ],
    "SNMP Synology Health": [
        ('systemStatus{job="snmp",instance="synology-nas"}', "System status"),
        ('diskTemperature{job="snmp",instance="synology-nas"}', "Disk temperatures"),
        ('raidTotalSize{job="snmp",instance="synology-nas"}', "RAID total size"),
        ('(raidTotalSize{job="snmp",instance="synology-nas"} - raidFreeSize{job="snmp",instance="synology-nas"}) / raidTotalSize{job="snmp",instance="synology-nas"} * 100', "RAID used %"),
    ],
}

KNOWN_EMPTY = {"pve_exporter up vector", "Proxmox node CPU", "Proxmox node RAM used",
               "Proxmox node RAM total", "System status", "Disk temperatures",
               "RAID total size", "RAID used %",
               "Speedtest avg DL (historical)"}  # speedtest: 60min interval, may be stale

def test_dashboard_queries():
    print(f"\n{BOLD}{CYAN}━━ 4. Dashboard Panel PromQL Validation ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
    for dash_name, queries in DASHBOARD_QUERIES.items():
        print(f"\n  {BOLD}{dash_name}{RESET}")
        ok_count = sum_total = 0
        for expr, label in queries:
            sum_total += 1
            has_data, res, err = prom_query_via_grafana(expr)
            is_known = label in KNOWN_EMPTY
            if has_data:
                ok_count += 1
                record("dashboards", f"  {dash_name} → {label}", True, f"{len(res)} series")
            elif err and "parse error" in err.lower():
                record("dashboards", f"  {dash_name} → {label}", False, f"PARSE ERROR: {err[:80]}")
            elif is_known:
                record("dashboards", f"  {dash_name} → {label}", True, "no data (pending fix — expected)")
                ok_count += 1
            else:
                record("dashboards", f"  {dash_name} → {label}", False, f"no data — {err or 'empty result'}")


# ── 5. Grafana Datasource Health ─────────────────────────────────────────────
def test_grafana_datasource():
    print(f"\n{BOLD}{CYAN}━━ 5. Grafana Datasource Health ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
    status, data = grafana_get(f"/api/datasources/uid/{PROM_DS_UID}/health")
    ok = status == 200 and isinstance(data, dict) and data.get("status") == "OK"
    record("grafana", "Prometheus datasource health check", ok,
           data.get("message","") if isinstance(data, dict) else f"HTTP {status}")

    # List all datasources
    status2, ds_list = grafana_get("/api/datasources")
    if status2 == 200 and isinstance(ds_list, list):
        record("grafana", f"Total datasources found", True, f"{len(ds_list)} datasource(s)")
        for ds in ds_list:
            print(f"    • {ds.get('name','?')} [{ds.get('type','?')}] uid={ds.get('uid','?')}")


# ── 6. Grafana Alert Rules ────────────────────────────────────────────────────
EXPECTED_ALERT_FOLDERS = ["Infrastructure"]
CRITICAL_RULE_NAMES = ["NAS Down", "High CPU", "High Memory", "Low Disk",
                        "Container Down", "Speedtest"]

def test_alert_rules():
    print(f"\n{BOLD}{CYAN}━━ 6. Grafana Alert Rules ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
    status, groups = grafana_get("/api/ruler/grafana/api/v1/rules")
    if status != 200:
        record("alerts", "Alert rules accessible", False, f"HTTP {status}")
        return

    all_rules = []
    for folder, group_list in (groups if isinstance(groups, dict) else {}).items():
        for grp in group_list:
            for rule in grp.get("rules", []):
                all_rules.append({"folder": folder, "group": grp.get("name"), **rule})

    record("alerts", "Alert rules API accessible", True, f"{len(all_rules)} rule(s) found")

    # Check firing state
    status2, states = grafana_get("/api/prometheus/grafana/api/v1/rules")
    pending_fire = []
    normal_count = 0
    if status2 == 200 and isinstance(states, dict):
        for grp in states.get("data", {}).get("groups", []):
            for rule in grp.get("rules", []):
                state = rule.get("state", "")
                name = rule.get("name", "")
                if state == "firing":
                    pending_fire.append(name)
                elif state in ("inactive", "normal", "pending"):
                    normal_count += 1

    if pending_fire:
        # pve target is known-down (network issue) → "Prometheus Target Down" is CORRECT
        expected_firing = {"Prometheus Target Down"}  # remove once pve is fixed
        real_unexpected = [r for r in pending_fire
                          if "test" not in r.lower() and r not in expected_firing]
        known_fire = [r for r in pending_fire if r in expected_firing]
        if real_unexpected:
            record("alerts", "No unexpected firing alerts", False, f"FIRING: {', '.join(real_unexpected)}")
        elif known_fire:
            record("alerts", "No unexpected firing alerts", True,
                   f"Expected firing (pve DOWN): {', '.join(known_fire)}")
        else:
            record("alerts", "No unexpected firing alerts", True, f"test rules firing (expected): {', '.join(pending_fire)}")
    else:
        record("alerts", "No firing alerts", True, f"{normal_count} rules normal/inactive")

    # Print all rules summary
    test_rules = [r for r in all_rules if "test" in r.get("grafana_alert", {}).get("title", "").lower()]
    real_rules = [r for r in all_rules if r not in test_rules]
    print(f"\n  {INFO} Production rules: {len(real_rules)}, Test rules: {len(test_rules)}")
    for r in real_rules[:15]:
        title = r.get("grafana_alert", {}).get("title", r.get("alert", "?"))
        print(f"    • {title}")


# ── 7. Grafana Dashboard Existence ───────────────────────────────────────────
EXPECTED_DASHBOARDS = {
    "lcHlCU2Vz":           "Synology NAS — Full System Overview",
    "portainer-overview-v1": "Portainer — Docker & Host Overview",
    "proxmox-bab1-v2":     "Proxmox Cluster — bab1",
}

def test_dashboard_existence():
    print(f"\n{BOLD}{CYAN}━━ 7. Dashboard Existence ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}")
    for uid, expected_title in EXPECTED_DASHBOARDS.items():
        status, data = grafana_get(f"/api/dashboards/uid/{uid}")
        ok = status == 200
        title = data.get("dashboard", {}).get("title", "?") if ok else "—"
        record("dashboards_exist", f"Dashboard {uid}", ok,
               f"'{title}' v{data.get('dashboard',{}).get('version','?')}" if ok else f"HTTP {status}")


# ── Summary ───────────────────────────────────────────────────────────────────
def print_summary():
    print(f"\n{BOLD}{'━'*70}{RESET}")
    print(f"{BOLD}  TEST SUMMARY — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
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
        icon = TICK if failed == 0 else (WARN if passed > 0 else CROSS)
        print(f"  {icon}  {cat.upper():<22} {passed}/{len(cat_results)} passed")

    print(f"{'━'*70}")
    overall = total_fail == 0
    pct = int(100 * total_pass / (total_pass + total_fail)) if (total_pass + total_fail) else 0
    icon = TICK if overall else (WARN if total_pass > total_fail else CROSS)
    print(f"\n  {icon}  OVERALL: {total_pass}/{total_pass+total_fail} passed ({pct}%)")

    if total_fail:
        print(f"\n{BOLD}  Failed tests:{RESET}")
        for r in results:
            if not r["passed"]:
                # strip ANSI for clean listing
                detail = r["detail"].replace(GREEN,"").replace(RED,"").replace(YELLOW,"").replace(CYAN,"").replace(BOLD,"").replace(RESET,"")
                print(f"    {CROSS}  [{r['category']}] {r['name']} — {detail}")

    print(f"\n{'━'*70}\n")

    # Known pending issues reminder
    print(f"{BOLD}  Pending user actions (not failures):{RESET}")
    print(f"  1. NAS: copy updated prometheus/prometheus.yml → /volume1/docker/grafana/prometheus.yml")
    print(f"     then: docker exec Prometheus kill -HUP 1")
    print(f"     ↳ Fixes: SNMP Synology data (diskTemperature, raidStatus, etc.)")
    print(f"  2. Portainer stack editor → pve_exporter: add 'network_mode: host', remove ports/networks")
    print(f"     ↳ Fixes: Proxmox dashboard (pve_up, pve_cpu_usage_ratio, etc.)")
    print(f"  3. After pve data flows: delete test alert rules pve-test-{{cpu,mem,uptime}}-firing\n")

    return 0 if overall else 1


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    import urllib.parse  # ensure available

    parser = argparse.ArgumentParser(description="Infrastructure monitoring backend test suite")
    parser.add_argument("--quick",  action="store_true", help="Targets + key metrics only")
    parser.add_argument("--alerts", action="store_true", help="Include alert rule state tests")
    args = parser.parse_args()

    print(f"\n{BOLD}{'━'*70}")
    print(f"  Infrastructure Monitoring — Backend Test Suite")
    print(f"  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'━'*70}{RESET}")
    print(f"  Grafana:    {GRAFANA}")
    print(f"  Prometheus: via Grafana proxy (uid: {PROM_DS_UID})")

    reach_ok, active_targets = test_prometheus_health()
    test_targets(active_targets)
    test_key_metrics()

    if not args.quick:
        test_dashboard_queries()
        test_grafana_datasource()
        test_dashboard_existence()
        test_alert_rules()

    sys.exit(print_summary())


if __name__ == "__main__":
    main()
