/**
 * MCP Servers Installer — VS Code Extension
 *
 * Commands:
 *   MCP: Install & Configure All MCP Servers  — run pip install -e . in each venv
 *   MCP: Write mcp.json for Current Workspace — write .vscode/mcp.json
 *   MCP: Start HTTP Gateway                   — start mcp_http_gateway.py
 *   MCP: Stop HTTP Gateway                    — kill the gateway process
 *   MCP: Show Server Status                   — quick-check all server binaries
 */
import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { ChildProcess, spawn, execFile } from 'child_process';

// ---------------------------------------------------------------------------
// Server registry
// ---------------------------------------------------------------------------

interface McpServerDef {
  name: string;
  dir: string;          // relative to repoRoot
  bin: string;          // relative to dir/.venv/bin/
  port: number;
}

const SERVER_DEFS: McpServerDef[] = [
  { name: 'portainer', dir: 'mcpportainer', bin: 'portainer-mcp', port: 9001 },
  { name: 'proxmox',   dir: 'mcpproxmox',   bin: 'proxmox-mcp',   port: 9002 },
  { name: 'synology',  dir: 'mcpsynology',  bin: 'synology-mcp',  port: 9003 },
  { name: 'authentik', dir: 'authentikmcp', bin: 'authentik-mcp', port: 9004 },
  { name: 'grafana',   dir: 'grafanamcp',   bin: 'grafana-mcp',   port: 9005 },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getRepoRoot(config: vscode.WorkspaceConfiguration): string {
  const configured = config.get<string>('repoRoot', '');
  if (configured) return configured;

  // Auto-detect: look for any workspace folder that contains mcpportainer/
  const workspaceFolders = vscode.workspace.workspaceFolders ?? [];
  for (const folder of workspaceFolders) {
    const candidate = path.join(folder.uri.fsPath, '..'); // one level up
    if (fs.existsSync(path.join(candidate, 'mcpportainer'))) {
      return candidate;
    }
    if (fs.existsSync(path.join(folder.uri.fsPath, 'mcpportainer'))) {
      return folder.uri.fsPath;
    }
  }
  return '';
}

function binPath(repoRoot: string, def: McpServerDef): string {
  return path.join(repoRoot, def.dir, '.venv', 'bin', def.bin);
}

function gatewayScript(repoRoot: string): string {
  return path.join(repoRoot, 'mcpcreations', 'mcp_http_gateway.py');
}

// ---------------------------------------------------------------------------
// Gateway process singleton
// ---------------------------------------------------------------------------

let gatewayProcess: ChildProcess | undefined;

function startGateway(repoRoot: string, outputChannel: vscode.OutputChannel): void {
  if (gatewayProcess && !gatewayProcess.killed) {
    vscode.window.showInformationMessage('MCP Gateway is already running.');
    return;
  }
  const script = gatewayScript(repoRoot);
  if (!fs.existsSync(script)) {
    vscode.window.showErrorMessage(`Gateway script not found: ${script}`);
    return;
  }
  const python3 = path.join(repoRoot, 'mcpportainer', '.venv', 'bin', 'python3');
  const python = fs.existsSync(python3) ? python3 : 'python3';

  gatewayProcess = spawn(python, [script], {
    cwd: path.join(repoRoot, 'mcpcreations'),
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  gatewayProcess.stdout?.on('data', (d: Buffer) => outputChannel.append(d.toString()));
  gatewayProcess.stderr?.on('data', (d: Buffer) => outputChannel.append(d.toString()));
  gatewayProcess.on('close', (code) => {
    outputChannel.appendLine(`MCP Gateway exited with code ${code}`);
    gatewayProcess = undefined;
  });

  outputChannel.show();
  vscode.window.showInformationMessage(
    'MCP HTTP Gateway started. Ports: portainer=9001 proxmox=9002 synology=9003 authentik=9004 grafana=9005'
  );
}

function stopGateway(): void {
  if (!gatewayProcess || gatewayProcess.killed) {
    vscode.window.showInformationMessage('MCP Gateway is not running.');
    return;
  }
  gatewayProcess.kill('SIGTERM');
  gatewayProcess = undefined;
  vscode.window.showInformationMessage('MCP Gateway stopped.');
}

// ---------------------------------------------------------------------------
// mcp.json writer
// ---------------------------------------------------------------------------

function writeMcpJson(
  repoRoot: string,
  enabled: string[],
  targetDir: string,
): void {
  const servers: Record<string, unknown> = {};
  for (const def of SERVER_DEFS) {
    if (enabled.includes(def.name)) {
      servers[def.name] = {
        type: 'stdio',
        command: binPath(repoRoot, def),
        env: {},
      };
    }
  }
  const mcpJson = { servers };
  const vscodDir = path.join(targetDir, '.vscode');
  fs.mkdirSync(vscodDir, { recursive: true });
  const dest = path.join(vscodDir, 'mcp.json');
  fs.writeFileSync(dest, JSON.stringify(mcpJson, null, 2) + '\n', 'utf8');
  vscode.window.showInformationMessage(`mcp.json written to ${dest}`);
}

// ---------------------------------------------------------------------------
// Installer — pip install -e . in each venv
// ---------------------------------------------------------------------------

async function installServers(
  repoRoot: string,
  outputChannel: vscode.OutputChannel,
): Promise<void> {
  outputChannel.show();
  for (const def of SERVER_DEFS) {
    const dir = path.join(repoRoot, def.dir);
    const pip = path.join(dir, '.venv', 'bin', 'pip');
    if (!fs.existsSync(pip)) {
      outputChannel.appendLine(`[${def.name}] venv not found — skipping (run: python -m venv .venv && pip install -e ".[dev]" in ${dir})`);
      continue;
    }
    outputChannel.appendLine(`[${def.name}] Installing…`);
    await new Promise<void>((resolve) => {
      execFile(pip, ['install', '-e', '.[dev]', '--quiet'], { cwd: dir }, (err, stdout, stderr) => {
        if (err) {
          outputChannel.appendLine(`[${def.name}] ERROR: ${stderr}`);
        } else {
          outputChannel.appendLine(`[${def.name}] OK`);
        }
        resolve();
      });
    });
  }
  vscode.window.showInformationMessage('All MCP servers installed.');
}

// ---------------------------------------------------------------------------
// Status check
// ---------------------------------------------------------------------------

async function showStatus(repoRoot: string): Promise<void> {
  const lines: string[] = ['MCP Server Status\n================='];
  for (const def of SERVER_DEFS) {
    const bin = binPath(repoRoot, def);
    const exists = fs.existsSync(bin);
    lines.push(`${exists ? '✓' : '✗'} ${def.name.padEnd(12)} ${exists ? bin : 'NOT INSTALLED'}`);
  }
  lines.push('');
  lines.push(`Gateway: ${gatewayProcess && !gatewayProcess.killed ? `running (pid ${gatewayProcess.pid})` : 'stopped'}`);
  vscode.window.showInformationMessage(lines.join('\n'), { modal: true });
}

// ---------------------------------------------------------------------------
// Extension lifecycle
// ---------------------------------------------------------------------------

export function activate(context: vscode.ExtensionContext): void {
  const config = vscode.workspace.getConfiguration('mcpServers');
  const outputChannel = vscode.window.createOutputChannel('MCP Servers');
  context.subscriptions.push(outputChannel);

  const repoRoot = getRepoRoot(config);

  // Auto-start gateway if configured
  if (config.get<boolean>('gatewayEnabled') && repoRoot) {
    startGateway(repoRoot, outputChannel);
  }

  context.subscriptions.push(
    vscode.commands.registerCommand('mcpServers.install', async () => {
      const root = getRepoRoot(vscode.workspace.getConfiguration('mcpServers'));
      if (!root) {
        vscode.window.showErrorMessage('Cannot detect mcp repo root. Set mcpServers.repoRoot in settings.');
        return;
      }
      await installServers(root, outputChannel);
    }),

    vscode.commands.registerCommand('mcpServers.configure', () => {
      const root = getRepoRoot(vscode.workspace.getConfiguration('mcpServers'));
      if (!root) {
        vscode.window.showErrorMessage('Cannot detect mcp repo root. Set mcpServers.repoRoot in settings.');
        return;
      }
      const cfg = vscode.workspace.getConfiguration('mcpServers');
      const enabled = cfg.get<string[]>('enabledServers', SERVER_DEFS.map(d => d.name));
      // Write to the first workspace folder, or the repo root
      const target = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? root;
      writeMcpJson(root, enabled, target);
    }),

    vscode.commands.registerCommand('mcpServers.startGateway', () => {
      const root = getRepoRoot(vscode.workspace.getConfiguration('mcpServers'));
      if (!root) { vscode.window.showErrorMessage('Cannot detect mcp repo root.'); return; }
      startGateway(root, outputChannel);
    }),

    vscode.commands.registerCommand('mcpServers.stopGateway', () => stopGateway()),

    vscode.commands.registerCommand('mcpServers.showStatus', () => {
      const root = getRepoRoot(vscode.workspace.getConfiguration('mcpServers'));
      if (!root) { vscode.window.showErrorMessage('Cannot detect mcp repo root.'); return; }
      showStatus(root);
    }),
  );
}

export function deactivate(): void {
  stopGateway();
}
