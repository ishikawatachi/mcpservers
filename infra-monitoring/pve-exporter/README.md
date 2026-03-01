# PVE Exporter - Proxmox → Prometheus Bridge

`prometheus-pve-exporter` connects to the Proxmox API using your service account token
and exposes all PVE metrics in Prometheus format.

## Step 1 — Copy the credential config to the NAS

SSH into your NAS and run:

```bash
sudo cp /dev/stdin /volume1/docker/grafana/pve.yml << 'EOF'
default:
  user: prometheus@pve
  token_name: prometheus
  token_value: 5610c6de-28ef-4a35-9260-7ca0ffc583ff
  verify_ssl: false
EOF
sudo chmod 600 /volume1/docker/grafana/pve.yml
```

(The file `pve-exporter/config.yml` in this repo contains the same content for reference.)

## Step 2 — Add pve-exporter to the monitoring stack

In Portainer, open the **monitoring** stack (id: 16) and add the `pve-exporter` service
to the compose file. The snippet is in `pve-exporter/docker-compose-service.yml`.

Or via SSH:

```bash
# Edit your monitoring stack compose and add the pve-exporter service block
# Then redeploy via Portainer UI or:
cd /data/compose/16
docker compose up -d pve-exporter
```

## Step 3 — Verify

```bash
# From NAS shell — pve-exporter should respond:
curl "http://localhost:9221/pve?target=pm.local.defaultvaluation.com&module=default"
# You should see lots of pve_* metrics
```
