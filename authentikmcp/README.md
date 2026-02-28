# Authentik MCP Server

MCP server for Authentik — lets Claude query and manage your local Authentik identity provider.

## What you need to get started (TODO tomorrow)

1. **API Token** — In Authentik: Admin Interface → Directory → Tokens → Create token (type: `API`). Copy the key shown once.
2. **Authentik URL** — e.g. `http://192.168.x.x:9000` (your local container's address/port).
3. Store both in the macOS Keychain: `bash scripts/setup_keychain.sh` (to be written).
4. Optional: set `AUTHENTIK_SSL_VERIFY=false` if your instance uses a self-signed certificate.
5. Install and run: `pip install -e ".[dev]"` then `authentik-mcp`.

## Planned MCP tools

| Tool | Description |
|---|---|
| `health_check` | Verify connectivity and token validity (`/api/v3/root/config/`) |
| `list_users` | List all users with status and metadata |
| `get_user` | Fetch a specific user by ID |
| `list_groups` | List all groups |
| `list_applications` | List all configured applications |
| `list_flows` | List authentication/enrollment flows |
| `list_providers` | List OAuth2 / SAML / LDAP providers |
| `list_tokens` | List API tokens (admin only) |

## Authentication

Authentik uses a **Bearer token** (`Authorization: Bearer <api-token>`).

All API endpoints are under `/api/v3/` — fully documented at `http://<your-host>/api/v3/` (OpenAPI/Swagger UI built in).
