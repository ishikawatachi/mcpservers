# proxmox-mcp

MCP server for Proxmox VE infrastructure management.

## Features

18 tools covering the full Proxmox VE API surface:

**Read / Introspection**
- `health_check` — validate connectivity and token validity
- `get_cluster_status` — cluster nodes overview with quorum status
- `list_nodes` — all nodes with CPU, RAM, disk summary  
- `get_node_status` — detailed hardware & resource usage for a node
- `list_vms` — QEMU VMs on a node
- `get_vm_status` — current power/resource state of a VM
- `list_lxc` — LXC containers on a node
- `get_lxc_status` — current power/resource state of an LXC container
- `list_storages` — storage pools on a node with usage stats
- `get_storage_content` — ISOs, templates, backups, VM disks in a storage
- `list_tasks` — recent cluster-wide task history

**Power Actions (QEMU VMs)**
- `start_vm`, `stop_vm`, `shutdown_vm`, `reboot_vm`

**Power Actions (LXC Containers)**
- `start_lxc`, `stop_lxc`, `shutdown_lxc`

## Security

API token stored in macOS Keychain under service name `proxmox-mcp`.  
Token format: `user@realm!tokenid=uuid` (e.g. `root@pam!mcp=<uuid>`)

## Setup

```bash
chmod +x scripts/setup_keychain.sh
./scripts/setup_keychain.sh
```

Or manually:
```bash
security add-generic-password -s proxmox-mcp -a proxmox-url   -w "https://pm.example.com" -U
security add-generic-password -s proxmox-mcp -a proxmox-token -w "root@pam!mcp=<uuid>" -U
```

## Configuration

Priority order:
1. Environment variables: `PROXMOX_URL`, `PROXMOX_TOKEN`, `PROXMOX_SSL_VERIFY`, `PROXMOX_TIMEOUT`
2. macOS Keychain (service: `proxmox-mcp`, accounts: `proxmox-url`, `proxmox-token`)
3. `~/.config/proxmox-mcp/config.yaml`

## Run

```bash
python -m proxmox_mcp.server
# or
proxmox-mcp
```
