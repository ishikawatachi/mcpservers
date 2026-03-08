# Discord Alerting via Grafana

## Overview

We configure:
1. **Grafana Contact Point** → Discord webhook
2. **Notification Policy** → routes all alerts to Discord
3. **Alert Rules** → specific conditions that fire alerts

Discord webhook: configured in Grafana (never commit the raw URL to git — use ENV or Grafana UI).

---

## Alert Rules (current state — 2026-03-08)

### Infrastructure Health (`folder: infrastructure`)

| Alert Name | UID | Condition | `for` | execErrState | Severity |
|------------|-----|-----------|-------|--------------|----------|
| Proxmox Node Down ✏️ | `cfeozyn9eayo0e` | `pve_up{job="pve"} == 0` | **5m** *(was 2m)* | **KeepLast** *(was Error)* | critical |
| **pve_exporter Unreachable** 🆕 | `pve-exporter-unreachable-v1` | `up{job="pve"} == 0` | 5m | KeepLast | warning |
| Proxmox Node Memory High | `efeozynfx1f5sa` | RAM > 90% for 15m | 15m | Error | warning |
| Proxmox Storage Critical | `efeozynnm85j4c` | Storage > 85% | 5m | Error | critical |
| Prometheus Target Down ✏️ | `prom-target-down-v2` | `up{job!="pve"} == 0` *(pve excluded)* | 5m | **KeepLast** | critical |
| NAS Host Memory Critical | `nas-mem-critical-v2` | RAM < 10% | 5m | Error | critical |
| NAS Host Memory High | `nas-mem-warning-v2` | RAM < 20% | 15m | Error | warning |
| NAS Host CPU High | `nas-cpu-high-v2` | CPU > 85% | 10m | Error | warning |
| NAS System Load High | `nas-load-high-v2` | load5 > 10 | 10m | Error | warning |
| NAS Temperature High | `nas-temp-high-v2` | temp > 70°C | 5m | Error | warning |
| UniFi WAN Latency High | `unifi-latency-high-v2` | latency > 50ms | 5m | Error | warning |
| UniFi Device Firmware Update | `unifi-upgrade-v2` | upgradable > 0 | 1m | Error | info |

### Wazuh Security (`folder: infrastructure`, `ruleGroup: Wazuh Security`) 🆕

| Alert Name | UID | Condition | `for` | Severity |
|------------|-----|-----------|-------|----------|
| Critical Security Alert | `wazuh-critical-alert-v1` | rule.level ≥ 12 in last 5m | 0s | critical |
| Auth Brute Force | `wazuh-auth-bruteforce-v1` | >10 auth failures in 5m | 2m | warning |
| Agent Disconnected | `wazuh-agent-disconnected-v1` | disconnect event in 10m | 5m | warning |
| macOS CIS Failures | `wazuh-cis-macos-failures-v1` | >5 CIS SCA fails in 1h | 0s | warning |
| Root Execution | `wazuh-root-execution-v1` | rootcheck event in 5m | 0s | warning |
| FIM Critical Change | `wazuh-fim-critical-v1` | system path file change in 5m | 0s | critical |

✏️ = Rule modified from original. See fix_proxmox_alerts.py for details.
🆕 = New rule added.

---

## Why We Changed Proxmox Alerting

### Root cause of false alarms

```
Prometheus scrapes pve_exporter (172.22.0.1:9221)
  → pve_exporter calls Proxmox API (192.168.110.110)
  → If Proxmox API is slow / restarting → TCP timeout (20s)
  → Prometheus marks up{job="pve"} = 0
  → With execErrState=Error: alert fires immediately
  → Discord notification: "Proxmox Node Down" 🔴
  → But the NODE is actually ONLINE, only the API was slow
```

### Fix applied

| Change | Effect |
|--------|--------|
| `Proxmox Node Down` `for`: 2m → 5m | Must be down 5 consecutive minutes before alerting |
| `Proxmox Node Down` `execErrState`: Error → KeepLast | Scrape error ≠ alert; keeps last known state |
| `Proxmox Node Down` `noDataState`: NoData → KeepLast | Missing metric ≠ alert |
| New `pve_exporter Unreachable` alert | Specifically catches when pve_exporter itself is unreachable vs. node being down |
| `Prometheus Target Down` query: `up` → `up{job!="pve"}` | Removes duplicate alarm when pve_exporter times out |

### Alert deduplication

Before the fix, a single pve_exporter timeout caused:
1. `Proxmox Node Down` fires (execErrState=Error)
2. `Prometheus Target Down` also fires (same root cause)

After the fix:
1. If pve_exporter is unreachable for 5m → only `pve_exporter Unreachable` fires (warning)
2. If Proxmox node is actually down for 5m → `Proxmox Node Down` fires (critical)

---

## Wazuh → Discord High-Value Alerts

All Wazuh rules use `execErrState=KeepLast` and `noDataState=OK` to prevent
alert fatigue when the Wazuh Indexer is temporarily unreachable.

### macOS CIS Benchmark Monitoring

The `wazuh-cis-macos-failures-v1` rule detects CIS compliance failures:
- Policy: `cis_apple_macOS_13.0.yml` (or later)
- Only alerts when **more than 5 checks fail** in a 1-hour window
- Expected to trigger after a fresh SCA scan (12h interval by default)

To check if the CIS benchmark is running on your MacBook:
```bash
# On the MacBook with Wazuh agent installed:
sudo /Library/Ossec/bin/agent_control -i   # shows SCA status
sudo grep -i "sca" /Library/Ossec/logs/ossec.log | tail -20
```

---

## Manual steps via Grafana UI (already done via API)

If you need to recreate:
1. Go to **Alerting** → **Contact points** → **Add contact point**
   - Name: `Discord`
   - Type: `Discord`
   - Webhook URL: (your webhook)

2. Go to **Alerting** → **Notification policies** → set **Default policy** to use `Discord`

3. Alert rules are created in the `infrastructure` folder in Grafana Alerting.

---

## Discord Message Format

```
🔴 FIRING: Proxmox Node Down (critical)
  pve_up metric has been 0 for 5 consecutive minutes on node bab1
  (Alert suppressed during scrape errors to reduce false positives.)

⚠️ FIRING: pve_exporter Cannot Reach Proxmox (warning)
  The Prometheus scrape of pve_exporter has been failing for 5 minutes.
  Check container logs: docker logs pve_exporter

🔴 FIRING: Wazuh Critical Security Alert (critical)
  One or more Wazuh alert(s) at level 12+ were fired in the last 5 minutes.
  Investigate immediately in the Wazuh dashboard.

⚠️ FIRING: macOS CIS Benchmark: New Failures Detected (warning)
  More than 5 CIS macOS benchmark checks failed in the last hour.
```

---

## Scripts (mcpcreations/)

| Script | What it does |
|--------|-------------|
| `fix_proxmox_alerts.py` | Apply all Proxmox alert improvements |
| `create_wazuh_datasource.py` | Register Wazuh Indexer in Grafana |
| `create_wazuh_dashboard.py` | Deploy Wazuh Security Operations dashboard |
| `create_wazuh_alerts.py` | Create all 6 Wazuh → Discord alert rules |

All scripts support `--dry-run` to preview without making changes.

