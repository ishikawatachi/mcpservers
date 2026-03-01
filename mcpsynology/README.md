# Synology DSM MCP Server

An **MCP (Model Context Protocol) server** that exposes Synology DiskStation Manager (DSM) management capabilities as structured tools for AI assistants.

Follows the same structure and conventions as the `mcpproxmox` and `mcpportainer` servers in this workspace.

---

## Features

| Tool | DSM API | Description |
|------|---------|-------------|
| `health_check` | `SYNO.API.Info` | Validate connectivity and PAT validity |
| `get_system_info` | `SYNO.DSM.Info` | Model, firmware, serial number, uptime |
| `get_system_utilization` | `SYNO.Core.System.Utilization` | CPU %, RAM, disk I/O, network I/O per interface |
| `get_storage_info` | `SYNO.Storage.CGI.Storage` | Volumes, RAID groups, disk health summary |
| `get_disk_info` | `SYNO.Storage.CGI.HddMan` | Per-disk S.M.A.R.T. status, temperature, model |
| `list_shares` | `SYNO.Core.Share` | Shared folders with size and encryption status |
| `list_packages` | `SYNO.Core.Package` | Installed packages and their running status |
| `list_scheduled_tasks` | `SYNO.Core.TaskScheduler` | Task Scheduler jobs with last-run status |
| `list_docker_containers` | `SYNO.Docker.Container` | Containers managed by Container Manager |
| `list_docker_images` | `SYNO.Docker.Image` | Docker images on the NAS |
| `list_files` | `SYNO.FileStation.List` | Browse files in a shared folder path |
| `get_security_status` | `SYNO.Core.SecurityScan.Status` | Security Advisor scan results |
| `get_backup_tasks` | `SYNO.Backup.Task` | Hyper Backup task status and last results |

---

## Authentication

This server uses **Personal Access Tokens (PAT)** — available in DSM 7.2.2 and later.

### Create a PAT in DSM

1. Open DSM → **Control Panel** → **Personal** → **Security** → **Account**
2. Scroll to **Personal Access Tokens**
3. Click **Add** → give it a name (e.g. `mcp-server`) → confirm
4. Copy the generated token (shown only once)

> For DSM versions before 7.2.2, username/password session auth is used instead.
> See `config.py` for details.

---

## Quick Start

```bash
cd mcpsynology

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in editable mode
pip install -e ".[dev]"

# Store credentials in macOS Keychain
./scripts/setup_keychain.sh

# Start the server
synology-mcp
```

## Configuration

**Priority order:** env vars → macOS Keychain → `~/.config/synology-mcp/config.yaml`

| Variable | Keychain account | Description |
|----------|-----------------|-------------|
| `SYNOLOGY_URL` | `synology-url` | Base URL e.g. `https://nas.local:5001` |
| `SYNOLOGY_TOKEN` | `synology-token` | Personal Access Token (PAT) |
| `SYNOLOGY_SSL_VERIFY` | — | Set to `false` to skip TLS verification (default `true`) |
| `SYNOLOGY_TIMEOUT` | — | Request timeout in seconds (default `30`) |

### YAML config example

```yaml
# ~/.config/synology-mcp/config.yaml
synology_url: "https://nas.local.example.com:5001"
ssl_verify: false
timeout: 30
```

---

## DSM API Notes

All DSM REST APIs live under: `https://NAS_IP:PORT/webapi/`

The PAT is sent as:
- `Authorization: Bearer <token>` header (DSM 7.2.2+)
- `_sid=<token>` query parameter (fallback for older CGI endpoints like `SYNO.Storage.CGI.*`)

API discovery endpoint:
```
GET /webapi/query.cgi?api=SYNO.API.Info&version=1&method=query&query=all
```

Response envelope pattern:
```json
{"success": true, "data": { ... }}
```

---

## MCP Client Configuration

Add to your `claude_desktop_config.json` (or equivalent):

```json
{
  "mcpServers": {
    "synology": {
      "command": "/path/to/mcpsynology/.venv/bin/synology-mcp"
    }
  }
}
```
