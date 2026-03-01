# Discord Alerting via Grafana

## Overview

We configure:
1. **Grafana Contact Point** → Discord webhook
2. **Notification Policy** → routes all alerts to Discord
3. **Alert Rules** → specific conditions that fire alerts

Discord webhook: configured in Grafana (never commit the raw URL to git — use ENV or Grafana UI).

---

## Alert Rules Created

| Alert Name | Condition | Severity |
|------------|-----------|----------|
| Proxmox Node Down | `pve_up == 0` | Critical |
| VM/LXC CPU High | Per-VM CPU > 90% for 10m | Warning |
| Node Memory High | Node RAM > 90% for 15m | Warning |
| Container Down (unexpected) | cAdvisor container disappears | Critical |
| Disk Usage Critical | Any PVE storage > 85% full | Warning |
| Portainer Endpoint Offline | `portainer` job down | Warning |

---

## Manual steps via Grafana UI (already done via API)

If you need to recreate:
1. Go to **Alerting** → **Contact points** → **Add contact point**
   - Name: `Discord`
   - Type: `Discord`
   - Webhook URL: (your webhook)
   - Message: `{{ template "discord.message" . }}`

2. Go to **Alerting** → **Notification policies** → set **Default policy** to use `Discord`

3. Alert rules are created in the `infra-alerts` folder in Grafana Alerting.

---

## Discord Message Format

Alerts will appear in Discord like:
```
🔴 FIRING: Proxmox Node Down
  Node bab1 is unreachable
  Instance: pm.local.defaultvaluation.com
  Since: 2026-03-01 12:00 UTC

⚠️ FIRING: Node Memory High  
  bab1 RAM usage: 94.2% (58.6/62.1 GB)
  Threshold: 90%
```
