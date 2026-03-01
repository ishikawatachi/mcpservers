# Prometheus Config Update

The full replacement `prometheus.yml` is in this folder.

## How to apply it

SSH into your NAS and run:

```bash
# Backup current config
cp /volume1/docker/grafana/prometheus.yml /volume1/docker/grafana/prometheus.yml.bak

# Copy new config
# (upload prometheus.yml from this folder first, e.g. via SCP or DSM File Station)
scp prometheus/prometheus.yml nas:/volume1/docker/grafana/prometheus.yml

# Reload Prometheus config WITHOUT restarting (no data loss):
curl -s -X POST http://localhost:9090/-/reload
# Or via docker:
docker exec Prometheus kill -HUP 1
```

## New scrape jobs added

| Job | Target | What it provides |
|-----|--------|-----------------|
| `pve` | `pve_exporter:9221` | Proxmox VE node, VM, LXC, storage metrics |
| `portainer` | host IP:9000 | Portainer EE container health, resource usage |

## Verify new targets are up

After reloading, visit: `http://<NAS-IP>:9090/targets`
All targets should show **UP** in green.
