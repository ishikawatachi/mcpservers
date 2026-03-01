# Infrastructure Monitoring Setup

This folder tracks all configuration for the Grafana + Prometheus monitoring stack
running on the Synology NAS (Docker endpoint 2, `local`).

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Synology NAS (Docker)                   │
│                                                          │
│  ┌──────────┐   ┌────────────┐   ┌──────────────────┐  │
│  │ Grafana  │◄──│ Prometheus │◄──│  pve-exporter    │  │
│  │ :3000    │   │ :9090      │   │  :9221           │  │
│  └──────────┘   └────────────┘   └──────────────────┘  │
│        │              │◄──── node-exporter (:9100)       │
│        │              │◄──── cAdvisor      (:8080)       │
│        │              │◄──── speedtest-exp (:9798)       │
│        │              │◄──── snmp-exporter (:9116)       │
│        │              │◄──── portainer     (:9000/metrics)│
│        │                                                 │
└────────┼────────────────────────────────────────────────┘
         │
         └──► Discord Webhook (alerting)
              Proxmox PVE: pm.local.defaultvaluation.com
```

## Stack Location on NAS

| File | NAS Path |
|------|----------|
| Prometheus config | `/volume1/docker/grafana/prometheus.yml` |
| Prometheus data | `/volume1/docker/grafana/prometheus/` |
| Grafana data | `/volume1/docker/grafana/data/` |
| PVE exporter config | `/volume1/docker/grafana/pve.yml` |
| Monitoring compose | Portainer stack `monitoring` (id: 16) |

## Dashboards

| Dashboard | UID | Description |
|-----------|-----|-------------|
| Proxmox Cluster Overview | `proxmox-bab1-v2` | Node, VM/LXC, storage, CPU/RAM |
| Portainer Overview | `portainer-overview-v1` | Containers, stacks, endpoints |
| cAdvisor (Docker) | `9AJV_mnIk` | Container metrics |
| Synology | `lcHlCU2Vz` | NAS disk, CPU |

## Setup Steps (ordered)

1. [Deploy pve-exporter](./pve-exporter/README.md)
2. [Update Prometheus config](./prometheus/README.md)
3. Grafana dashboards are created automatically via MCP
4. [Enable Portainer metrics endpoint](./portainer/README.md)
5. [Discord alerting](./alerting/README.md)
