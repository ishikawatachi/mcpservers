# Portainer Metrics for Prometheus

Portainer EE exposes a native `/metrics` endpoint. We need to:
1. Create a Portainer API token
2. Add Portainer to the `prometheus_net` Docker network (so Prometheus can reach it)
3. Add a bearer token to `prometheus.yml`

## Step 1 — Create a Portainer API token

1. Log into Portainer at `https://portainer.local.defaultvaluation.com`
2. Go to **My Account** (top right) → **Access tokens** → **Add access token**
3. Name it `prometheus-scraper`
4. Copy the token — you'll only see it once!
5. Update `prometheus/prometheus.yml` → replace `REPLACE_WITH_PORTAINER_API_TOKEN`

## Step 2 — Connect Portainer to prometheus_net

Portainer runs on the default bridge network. Prometheus is on `prometheus_net`.
Run this on your NAS to bridge them:

```bash
docker network connect prometheus_net portainer
```

Then update the target in `prometheus.yml` from `172.17.0.3:9000` to `portainer:9000`:

```yaml
  - job_name: "portainer"
    metrics_path: /metrics
    bearer_token: "your-token-here"
    static_configs:
      - targets: ["portainer:9000"]
```

After reloading Prometheus, verify by visiting:
`http://<NAS-IP>:9090/targets` — `portainer` job should be **UP**.

## Step 3 — Reload Prometheus

```bash
docker exec Prometheus kill -HUP 1
```

## What metrics Portainer EE exposes

Key metrics available at `/metrics`:
- `portainer_containers_total` - total containers per endpoint
- `portainer_containers_running_total` - running containers
- `portainer_containers_stopped_total` - stopped containers
- `portainer_stacks_total` - stacks count
- `portainer_images_total` - images per endpoint
- `portainer_endpoints_total` - connected endpoints
- Plus standard Go runtime metrics (`go_*`, `process_*`)
