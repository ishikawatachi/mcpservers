# mcpcreations — Requirements & Changelog

## Overview

Python scripts that create and maintain Grafana dashboards, alert rules, and
datasources for the home-lab monitoring stack. Managed via the Grafana MCP
server (`grafanamcp`).

---

## Components

### Existing

| Script | Purpose |
|--------|---------|
| `create_proxmox_dashboard.py` | Deploy Proxmox cluster dashboard |
| `proxmox_dashboard.json` | Proxmox dashboard (original) |
| `proxmox_dashboard_v2.json` | Proxmox dashboard v2 (improved) |

### Added (2026-03-08)

| Script | Purpose |
|--------|---------|
| `fix_proxmox_alerts.py` | Fix pve_exporter false-positive alarms |
| `create_wazuh_datasource.py` | Register Wazuh Indexer in Grafana |
| `create_wazuh_dashboard.py` | Deploy Wazuh Security dashboard |
| `wazuh_dashboard.json` | Wazuh Security Operations dashboard |
| `create_wazuh_alerts.py` | Create Wazuh → Discord alert rules |

---

## Proxmox / pve_exporter Alert Improvements

### Problem

Three sources of false-positive Discord alarms from Proxmox monitoring:

1. **Proxmox Node Down** (`cfeozyn9eayo0e`): `execErrState=Error` + `for=2m`
   - When `pve_exporter` has a TCP timeout reaching the Proxmox API, Prometheus
     fails to scrape the job. With `execErrState=Error`, Grafana immediately
     fires the alert even though the *node* is fine — only the *exporter*
     connectivity is broken.
   - A `for=2m` window means even a brief Proxmox restart or maintenance
     window triggers an alert.

2. **Prometheus Target Down** (`prom-target-down-v2`): catches `up{...} < 1`
   for ALL jobs. When `pve_exporter` fails its Proxmox API call, the `pve` job's
   `up` metric drops to 0 → this alert also fires, doubling the Discord noise.

3. **No dedicated alert** for `pve_exporter` itself being unreachable (container
   restart, config errors) vs. Proxmox being unreachable.

### Changes Applied by `fix_proxmox_alerts.py`

| Alert | Field | Before | After | Reason |
|-------|-------|--------|-------|--------|
| Proxmox Node Down | `for` | `2m` | `5m` | Tolerates brief restarts & maintenance |
| Proxmox Node Down | `execErrState` | `Error` | `KeepLast` | Scrape errors ≠ node down |
| Proxmox Node Down | `noDataState` | `NoData` | `KeepLast` | Metric absence ≠ node down |
| Prometheus Target Down | query expr | `up` | `up{job!="pve"}` | Deduplicate; pve has own alert |
| Prometheus Target Down | `execErrState` | `Error` | `KeepLast` | Less noise on transient issues |
| **NEW** pve_exporter Unreachable | `for` | — | `5m` | Correctly scoped connectivity alert |
| **NEW** pve_exporter Unreachable | `severity` | — | `warning` | Not necessarily node outage |
| **NEW** pve_exporter Unreachable | `noDataState` | — | `OK` | No alert when exporter just started |

**Discord impact**: Fewer duplicate and false-positive notifications for
Proxmox during pve_exporter connectivity hiccups. The new `pve_exporter
Unreachable` alert tells you precisely *where* the connectivity broke.

---

## Wazuh Security Integration

### Wazuh Container Situation

Wazuh is referenced in the user's environment but not found as a Docker
container in either Portainer endpoint (local NAS or bab1docker). Possible
deployment modes:
- **Proxmox LXC container** running Wazuh Manager + Indexer (not Docker-managed)
- **Native install** on a server
- **Docker Compose** outside Portainer management scope

The integration scripts are ready to deploy once the Wazuh Indexer URL is
accessible from Grafana. Set `WAZUH_INDEXER_URL` before running.

### Wazuh Architecture Assumed

```
macOS Agent (your MacBook)  ─┐
Linux/Server Agents          ├─→  Wazuh Manager (port 1514/1515)
Proxmox Agents               ┘        │
                                       ↓
                               Wazuh Indexer (OpenSearch, port 9200)
                                       │
                               Wazuh Dashboard (port 443)
                                       │
                               Grafana (Elasticsearch datasource)
                                       │
                               Discord (via alert rules)
```

### Datasource Requirements

| Field | Value |
|-------|-------|
| Type | Elasticsearch (OpenSearch-compatible) |
| UID | `wazuh-indexer` |
| URL | `https://wazuh-indexer.local.defaultvaluation.com:9200` |
| Auth | Basic — admin / `<WAZUH_INDEXER_PASS>` |
| Index | `wazuh-alerts-*` |
| Time field | `@timestamp` |

### Wazuh Dashboard Panels

| Panel | Query | Purpose |
|-------|-------|---------|
| Total Alerts (24h) | `*` count | Overview stat |
| Critical Alerts | `rule.level:[12 TO 15]` | Severity filter |
| High Alerts | `rule.level:[8 TO 11]` | Severity filter |
| Auth Failures | `rule.groups:authentication_failed` | Security trend |
| FIM Events | `rule.groups:syscheck` | File integrity |
| SCA Failures | `rule.groups:sca AND result:failed` | Compliance |
| Alert Timeline | Severity breakdown time series | Trend analysis |
| Top 10 Rules | Terms aggregation on rule.description | Noise ranking |
| Auth Failure IPs | Terms on data.srcip | Source analysis |
| CIS macOS Failed | `cis_apple*` SCA failures | macOS compliance |
| CIS macOS Passed | `cis_apple*` SCA passes | Compliance score |
| FIM Timeline | syscheck added/modified/deleted | Change tracking |

### CIS macOS Benchmark

Wazuh evaluates macOS agents via its Security Configuration Assessment (SCA)
module. To enable CIS Apple macOS benchmarks on the Mac agent:

1. Install the Wazuh agent on the Mac:
   ```bash
   /Library/Ossec/bin/ossec-control start
   ```

2. Edit `/Library/Ossec/etc/ossec.conf` and enable SCA:
   ```xml
   <sca>
     <enabled>yes</enabled>
     <interval>12h</interval>
     <policies>
       <policy>cis_apple_macOS_13.0.yml</policy>
     </policies>
   </sca>
   ```

3. Wazuh ships with policies in `/Library/Ossec/ruleset/sca/`:
   - `cis_apple_macOS_13.0.yml` (Ventura)
   - `cis_apple_macOS_14.0.yml` (Sonoma) — if available

4. Results appear in `wazuh-alerts-*` index under `rule.groups: sca` within
   one SCA scan interval.

### Wazuh Alert Rules → Discord

| Rule UID | Title | Level | `for` | Trigger |
|----------|-------|-------|-------|---------|
| `wazuh-critical-alert-v1` | Critical Alert | 🔴 critical | 0s | Any level 12–15 event in 5 min |
| `wazuh-auth-bruteforce-v1` | Auth Brute Force | ⚠️ warning | 2m | >10 auth failures in 5 min |
| `wazuh-agent-disconnected-v1` | Agent Disconnected | ⚠️ warning | 5m | Agent disconnect event (rule 504/506) |
| `wazuh-cis-macos-failures-v1` | macOS CIS Failures | ⚠️ warning | 0s | >5 CIS check failures in 1 hour |
| `wazuh-root-execution-v1` | Root Execution | ⚠️ warning | 0s | Any root command via rootcheck/audit |
| `wazuh-fim-critical-v1` | FIM Critical Change | 🔴 critical | 0s | System binary/config file modified |

All rules use:
- `execErrState: KeepLast` — no false alarms if Wazuh Indexer is temporarily unreachable
- `noDataState: OK` — no alarm if index has no recent events (expected during quiet periods)
- `team: security` label — for future routing/silencing differentiation

---

## Test Suite

### Location

```
mcpcreations/
└── tests/
    ├── __init__.py
    ├── run_tests.sh               ← master runner
    ├── test_proxmox_alerts.py    ← before/after tests for pve_exporter alert fixes
    └── test_wazuh.py             ← before/after tests for Wazuh integration
```

### Workflow

```bash
# Step 0: Confirm baseline (before any changes)
bash tests/run_tests.sh before

# Step 1: Apply Proxmox alert fixes
python3 fix_proxmox_alerts.py

# Step 2: Set up Wazuh (requires Wazuh Indexer running)
export WAZUH_INDEXER_PASS="<password>"
python3 create_wazuh_datasource.py
python3 create_wazuh_dashboard.py
python3 create_wazuh_alerts.py

# Step 3: Confirm all improvements are applied
bash tests/run_tests.sh after
```

### Dry-run mode

All scripts support `--dry-run` to preview changes without writing to Grafana:

```bash
python3 fix_proxmox_alerts.py --dry-run
python3 create_wazuh_datasource.py --dry-run
python3 create_wazuh_dashboard.py --dry-run
python3 create_wazuh_alerts.py --dry-run
```

---

## Dependencies

All scripts reuse the `grafanamcp` virtual environment:

```
grafanamcp/.venv/
  └── httpx, structlog, mcp, pydantic
```

No additional packages are required.

---

## Environment Variables Reference

| Variable | Used By | Default |
|----------|---------|---------|
| `GRAFANA_TOKEN` | (test scripts) | from Keychain via config.py |
| `WAZUH_INDEXER_URL` | `create_wazuh_datasource.py` | `https://wazuh-indexer.local.defaultvaluation.com:9200` |
| `WAZUH_INDEXER_USER` | `create_wazuh_datasource.py` | `admin` |
| `WAZUH_INDEXER_PASS` | `create_wazuh_datasource.py` | **Required — no default** |

---

## Changelog

| Date | Change |
|------|--------|
| 2026-03-08 | Initial: `create_proxmox_dashboard.py` + `proxmox_dashboard*.json` |
| 2026-03-08 | Added: `fix_proxmox_alerts.py` — reduces pve_exporter false alarms |
| 2026-03-08 | Added: Wazuh integration scripts (datasource, dashboard, alerts) |
| 2026-03-08 | Added: `tests/` directory with before/after test suites |
