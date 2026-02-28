# Portainer MCP Server

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server that gives Claude / GitHub Copilot Chat programmatic access to your Portainer infrastructure.

## Features

| Tool | Description |
|---|---|
| `health_check` | Validate connectivity and token validity |
| `list_endpoints` | List all Portainer environments |
| `list_containers` | List containers on an endpoint |
| `inspect_container` | Full container inspection |
| `start_container` | Start a stopped container |
| `stop_container` | Stop a running container |
| `container_logs` | Retrieve container log output |
| `list_images` | List Docker images on an endpoint |
| `list_stacks` | List all Compose stacks |
| `deploy_stack` | Create or update a Compose stack |

## Requirements

- macOS (Keychain integration required)
- Python 3.10+
- Access to a Portainer instance with an API token (`ptr_…`)

## Installation

```bash
# 1. Clone / open the workspace
cd mcpportainer

# 2. Create a virtual environment and install
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Credential Setup

Credentials are stored in your macOS Keychain — never in plaintext files.

### Option A — interactive script (recommended for first-time setup)

```bash
chmod +x scripts/setup_keychain.sh
./scripts/setup_keychain.sh
```

### Option B — manual `security` commands

```bash
# Store the Portainer URL
security add-generic-password -s "portainer-mcp" -a "portainer-url" \
    -w "https://pr.local.defaultvaluation.com"

# Store the API token
security add-generic-password -s "portainer-mcp" -a "portainer-token" \
    -w "ptr_YOUR_TOKEN_HERE"
```

### Option C — environment variables (CI/CD)

```bash
export PORTAINER_URL="https://pr.local.defaultvaluation.com"
export PORTAINER_TOKEN="ptr_YOUR_TOKEN_HERE"
```

### Option D — YAML config file

Create `~/.config/portainer-mcp/config.yaml`:

```yaml
portainer_url: "https://pr.local.defaultvaluation.com"
ssl_verify: true        # set false only for self-signed certs in dev
timeout: 30.0
```

> **Never** put `api_token` in the YAML file — use Keychain or env var.

## Running

```bash
# From within the venv
portainer-mcp

# Or directly:
python -m portainer_mcp.server
```

## Configuring Claude / VS Code Copilot

Add to your MCP client configuration (e.g. `~/.claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "portainer": {
      "command": "/path/to/.venv/bin/portainer-mcp",
      "env": {}
    }
  }
}
```

SSL verification is **enabled by default** — the Portainer instance uses a valid Let's Encrypt certificate. Only set `PORTAINER_SSL_VERIFY=false` for genuine self-signed/dev certificates.

## Running Tests

```bash
pytest -v
```

## Project Structure

```
mcpportainer/
├── REQUIREMENTS.md          # Project requirements
├── README.md
├── pyproject.toml
├── scripts/
│   └── setup_keychain.sh    # Interactive credential setup
├── src/
│   └── portainer_mcp/
│       ├── __init__.py
│       ├── server.py        # MCP server + tool definitions
│       ├── client.py        # Portainer async HTTP client
│       ├── keychain.py      # macOS Keychain integration
│       ├── config.py        # Settings resolution
│       └── models.py        # Pydantic input/output models
└── tests/
    ├── test_keychain.py
    ├── test_client.py
    └── test_models.py
```

## Security Notes

- API token is retrieved from Keychain at runtime — never stored in plaintext
- All inputs are validated with Pydantic before reaching the API client
- Logs are structured JSON to stderr; tokens are never logged
- SSL verification is enabled by default; disable only for dev with `PORTAINER_SSL_VERIFY=false`
- The server runs with the permissions of the invoking user — follow least-privilege principles when creating the Portainer API token
