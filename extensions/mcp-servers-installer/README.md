# MCP Servers Installer — VS Code Extension

A `.vsix` extension that installs, configures, and manages all five MCP servers (portainer, proxmox, synology, authentik, grafana) from within VS Code.

## Commands

| Command | Description |
|---|---|
| **MCP: Install & Configure All MCP Servers** | Runs `pip install -e .[dev]` in each server's venv |
| **MCP: Write mcp.json for Current Workspace** | Writes `.vscode/mcp.json` pointing at all server binaries |
| **MCP: Start HTTP Gateway** | Starts `mcp_http_gateway.py` for external access |
| **MCP: Stop HTTP Gateway** | Stops the running gateway |
| **MCP: Show Server Status** | Reports which server binaries are installed |

## Build & Install

```bash
cd extensions/mcp-servers-installer

# Install Node dependencies
npm install

# Compile TypeScript
npm run compile

# Package as VSIX
npm run package
# → mcp-servers-installer-0.1.0.vsix

# Install in VS Code
code --install-extension mcp-servers-installer-0.1.0.vsix
```

## Settings

| Setting | Default | Description |
|---|---|---|
| `mcpServers.repoRoot` | `""` (auto-detect) | Absolute path to `git/mcp/` |
| `mcpServers.enabledServers` | all five | Which servers to include in mcp.json |
| `mcpServers.gatewayEnabled` | `false` | Auto-start HTTP gateway on activation |

## mcp.json locations

VS Code discovers `mcp.json` in the following order (highest priority first):

1. **User settings** — `~/Library/Application Support/Code/User/settings.json`  
   Key: `"github.copilot.chat.mcpServers": { … }`  
   _Applies to every workspace. Ideal for personal machines._

2. **Workspace folder** — `.vscode/mcp.json` inside an open folder  
   _Applies only when that folder is open. Best for repo-scoped config._  
   Current location: `mcpportainer/.vscode/mcp.json`

3. **Multi-root workspace file** — embedded in `mcpportainer.code-workspace`  
   Key: `"mcp": { "servers": { … } }`

The extension's **"Write mcp.json"** command writes option 2 for the currently active workspace folder.

## External access (outside VS Code)

### Stdio clients (Claude Desktop, nanoclaw, openclaw)

Add to `~/.config/nanoclaw/config.json` or `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "portainer": {
      "command": "/path/to/git/mcp/mcpportainer/.venv/bin/portainer-mcp"
    },
    "proxmox": {
      "command": "/path/to/git/mcp/mcpproxmox/.venv/bin/proxmox-mcp"
    }
  }
}
```

### HTTP clients (Perplexity connector)

1. Start the gateway via the extension command or directly:
   ```bash
   python mcpcreations/mcp_http_gateway.py
   ```
2. Add to your Perplexity MCP settings:
   ```json
   {
     "mcpServers": {
       "portainer": { "url": "http://127.0.0.1:9001/mcp" },
       "proxmox":   { "url": "http://127.0.0.1:9002/mcp" },
       "synology":  { "url": "http://127.0.0.1:9003/mcp" },
       "authentik": { "url": "http://127.0.0.1:9004/mcp" },
       "grafana":   { "url": "http://127.0.0.1:9005/mcp" }
     }
   }
   ```

### nanoclaw notes

- Supports both `stdio` and `http` transport natively
- Tested with MCP protocol version `2024-11-05`  
- No special configuration needed beyond the command path

### openclaw notes

- Community fork; supports the same stdio + SSE transport
- Tool approval flow is identical to nanoclaw
- Point it at the binary or the gateway URL

## Testing external access

```bash
# Category 1+2: binary presence + stdio JSON-RPC
pytest mcpcreations/tests/test_mcp_external.py -v -m "not gateway"

# Category 3+4: HTTP gateway + Perplexity format (start the gateway first)
python mcpcreations/mcp_http_gateway.py &
pytest mcpcreations/tests/test_mcp_external.py -v -m gateway
```
