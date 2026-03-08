# Deployments

Infrastructure deployment scripts and compose files, deployed via Portainer MCP.

## Contents

| Directory | Stack | Access |
|---|---|---|
| [wazuh/](wazuh/) | Wazuh 4.9 (SIEM — manager + indexer + dashboard) | Synology reverse proxy |

## Conventions

Each deployment directory contains:

| File | Purpose |
|---|---|
| `docker-compose.yml` | The Compose stack definition |
| `.env.example` | Template of required environment variables |
| `config.yml` | Stack-specific configuration (cert gen config, etc.) |
| `deploy_<name>.py` | Python deployment script using the portainer-mcp client |
| `README.md` | Per-stack documentation |
| `tests/` | pytest suite (offline + live phases) |

## Deploy via Portainer MCP

All deploy scripts use `portainer_mcp.client` from the portainer-mcp venv.  
Activate it before running any deploy script:

```bash
source mcpportainer/.venv/bin/activate
```

## Test phases (all stacks)

| pytest mark | Requires | Description |
|---|---|---|
| `offline` | nothing | Compose file structure validation |
| `live` | Portainer running | Connection + endpoint discovery |
| `deploy` | Portainer + `live` | Actually deploys (destructive) |
| `postdeploy` | Deployed stack | Health checks on running containers |
