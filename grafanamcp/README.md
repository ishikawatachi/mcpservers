# Grafana MCP Server

MCP server for Grafana — lets Claude query and manage your local Grafana instance.

## What you need to get started (TODO tomorrow)

1. **Service Account Token** — In Grafana: Administration → Users and access → Service Accounts → Add service account → create a token with `Editor` or `Viewer` role.
2. **Grafana URL** — e.g. `http://192.168.x.x:3000` (your local container's address/port).
3. Store both in the macOS Keychain: `bash scripts/setup_keychain.sh` (to be written).
4. Optional: set `GRAFANA_SSL_VERIFY=false` if your instance uses a self-signed certificate.
5. Install and run: `pip install -e ".[dev]"` then `grafana-mcp`.

## Planned MCP tools

| Tool | Description |
|---|---|
| `health_check` | Verify connectivity and token validity |
| `list_dashboards` | Search/list all dashboards |
| `get_dashboard` | Fetch a dashboard by UID |
| `list_datasources` | List configured data sources |
| `list_alerts` | List alert rules |
| `list_annotations` | Query annotations |
| `list_folders` | List dashboard folders |
| `list_users` | List Grafana users (admin token required) |

## Authentication

Grafana uses a **Bearer token** (`Authorization: Bearer <service-account-token>`).

Token format: a long alphanumeric string — no special format required.
