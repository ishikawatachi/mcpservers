# Wazuh Single-Node Deployment

Deploys Wazuh 4.9 (manager + indexer + dashboard) as a Portainer stack.  
The dashboard is exposed via the Synology reverse proxy on a custom hostname.

## Architecture

```
Synology DSM Reverse Proxy
  └─► wazuh.local.yourdomain.com:443  ──► wazuh-dashboard:5601  (proxy network)
                                               │
                                         wazuh-internal (bridge, isolated)
                                               │
                                 ┌─────────────┴──────────────┐
                           wazuh-manager               wazuh-indexer
                           (ports 1514,1515,55000)     (port 9200 internal)
                                 │
                           watchtower-wazuh  (auto-update weekly)
```

## Prerequisites

1. Docker is running on the target host with the `proxy` external network:
   ```bash
   docker network create proxy
   ```
2. Portainer is accessible and configured (API token in macOS Keychain)
3. The portainer-mcp venv is installed:
   ```bash
   cd mcpportainer && python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
   ```

## Deployment

### Option A — via deploy_wazuh.py (uses Portainer API)

```bash
# Activate portainer-mcp venv
source mcpportainer/.venv/bin/activate

# Deploy (use --endpoint-id to target a specific Portainer environment)
python mcpcreations/deployments/wazuh/deploy_wazuh.py \
  --hostname wazuh.local.yourdomain.com \
  --indexer-password 'SecureIndexerPass1!' \
  --dashboard-password 'SecureDashPass1!'

# Dry-run first
python mcpcreations/deployments/wazuh/deploy_wazuh.py \
  --hostname wazuh.local.yourdomain.com \
  --indexer-password 'SecureIndexerPass1!' \
  --dashboard-password 'SecureDashPass1!' \
  --dry-run
```

### Option B — via Portainer UI

1. Open Portainer → Stacks → Add Stack → Upload Compose
2. Upload `docker-compose.yml`
3. Set environment variables:
   - `WAZUH_HOSTNAME=wazuh.local.yourdomain.com`
   - `INDEXER_PASSWORD=SecureIndexerPass1!`
   - `DASHBOARD_PASSWORD=SecureDashPass1!`
4. Deploy

### Option C — direct docker compose (on the Docker host)

```bash
cp .env.example .env
# Edit .env with your values
docker compose up -d
```

## Synology Reverse Proxy Setup

In DSM → Control Panel → Application Portal → Reverse Proxy:

| Field | Value |
|---|---|
| Source protocol | HTTPS |
| Source hostname | `wazuh.local.yourdomain.com` |
| Source port | `443` |
| Destination protocol | HTTP |
| Destination hostname | `<docker-host-ip>` |
| Destination port | `5601` |

Enable "WebSocket support" if the dashboard uses WebSockets.

Generate a Synology Let's Encrypt certificate for the hostname under  
DSM → Control Panel → Security → Certificate → Add.

## First Login

- URL: `https://wazuh.local.yourdomain.com`
- Username: `admin`
- Password: your `DASHBOARD_PASSWORD`

## Testing

```bash
# Phase 1 — offline compose validation (no Portainer needed)
python -m pytest mcpcreations/deployments/wazuh/tests/ -v -m offline

# Phase 2 — Portainer connection test
python -m pytest mcpcreations/deployments/wazuh/tests/ -v -m "live and not deploy"

# Phase 3 — full deployment (runs deploy_wazuh.py, destructive)
PORTAINER_ENDPOINT_ID=1 \
WAZUH_HOSTNAME=wazuh.local.yourdomain.com \
INDEXER_PASSWORD='SecureIndexerPass1!' \
DASHBOARD_PASSWORD='SecureDashPass1!' \
python -m pytest mcpcreations/deployments/wazuh/tests/ -v -m "live and deploy"

# Phase 4 — post-deploy health check
WAZUH_HOSTNAME=wazuh.local.yourdomain.com \
python -m pytest mcpcreations/deployments/wazuh/tests/ -v -m postdeploy
```

## Networking Details

| Network | Type | Purpose |
|---|---|---|
| `wazuh-internal` | Bridge (internal) | Isolated inter-service communication; no internet in/out |
| `proxy` | External (pre-existing) | Shared with Synology reverse proxy; dashboard is reachable here |

## Watchtower

Watchtower checks for Wazuh image updates every 7 days and restarts updated containers.  
It is scoped only to the Wazuh containers (`wazuh-manager wazuh-indexer wazuh-dashboard`).

To disable watchtower, remove the `watchtower` service from `docker-compose.yml`.

## Agent Ports

| Port | Protocol | Purpose |
|---|---|---|
| `1514` | UDP | Syslog / event collection from agents |
| `1515` | TCP | Agent enrollment |
| `55000` | TCP | Wazuh REST API (restrict via firewall to internal networks only) |

Ensure your firewall rules allow agents on your network to reach ports 1514 and 1515 on the Docker host.  
Port 55000 **must not** be exposed to the internet.
