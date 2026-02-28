"""
Proxmox VE MCP Server — main entry point.

Exposes the following MCP tools:

  Read / Introspection
  ─────────────────────
  1.  health_check         — validate connectivity and token validity
  2.  get_cluster_status   — cluster nodes overview with quorum status
  3.  list_nodes           — list all Proxmox nodes with resource summary
  4.  get_node_status      — detailed resource usage for a specific node
  5.  list_vms             — list all QEMU VMs on a node
  6.  get_vm_status        — current power/resource state of a VM
  7.  list_lxc             — list all LXC containers on a node
  8.  get_lxc_status       — current power/resource state of an LXC container
  9.  list_storages        — list storage pools on a node
  10. get_storage_content  — list ISOs, templates, backups and VM disks
  11. list_tasks           — recent cluster-wide task history

  Power Actions (QEMU VMs)
  ─────────────────────────
  12. start_vm             — power on a stopped VM
  13. stop_vm              — force-stop (hard power-off) a VM
  14. shutdown_vm          — graceful ACPI shutdown with configurable timeout
  15. reboot_vm            — reboot a running VM

  Power Actions (LXC Containers)
  ────────────────────────────────
  16. start_lxc            — start a stopped LXC container
  17. stop_lxc             — force-stop an LXC container
  18. shutdown_lxc         — graceful shutdown with configurable timeout

Run:
    python -m proxmox_mcp.server
    # or via the installed script:
    proxmox-mcp
"""
from __future__ import annotations

import json
import logging
import sys

import structlog
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
from pydantic import ValidationError

from proxmox_mcp.client import ProxmoxAPIError, ProxmoxClient
from proxmox_mcp.config import get_settings
from proxmox_mcp.models import NodeInput, VmInput, ShutdownVmInput, StorageInput

# ---------------------------------------------------------------------------
# Logging setup — structured JSON to stderr, never to stdout (MCP uses stdout)
# ---------------------------------------------------------------------------

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
)

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

app = Server("proxmox-mcp")


def _ok(data: object) -> list[types.TextContent]:
    """Wrap a result as a JSON TextContent response."""
    return [types.TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _err(message: str) -> list[types.TextContent]:
    """Wrap an error message as a TextContent response."""
    return [types.TextContent(type="text", text=json.dumps({"error": message}))]


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    """Advertise all available tools to the MCP client."""
    return [
        # ── Health ──────────────────────────────────────────────────────────
        types.Tool(
            name="health_check",
            description=(
                "Validate Proxmox connectivity and API token validity. "
                "Returns Proxmox VE version and release information."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),

        # ── Cluster ─────────────────────────────────────────────────────────
        types.Tool(
            name="get_cluster_status",
            description=(
                "Return cluster-wide status including all nodes, their online/offline "
                "state, quorum votes, and cluster name."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="list_tasks",
            description="Return recent cluster-wide task history (up to 50 tasks by default).",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of tasks to return (default 50, max 200)",
                        "minimum": 1,
                        "maximum": 200,
                    },
                },
                "required": [],
            },
        ),

        # ── Nodes ───────────────────────────────────────────────────────────
        types.Tool(
            name="list_nodes",
            description=(
                "List all Proxmox nodes in the cluster with CPU, memory, disk usage "
                "summary and uptime."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="get_node_status",
            description=(
                "Return detailed resource usage and hardware information for a specific "
                "Proxmox node (CPU, memory, disk, kernel, PVE version)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Proxmox node name"},
                },
                "required": ["node"],
            },
        ),

        # ── QEMU VMs ────────────────────────────────────────────────────────
        types.Tool(
            name="list_vms",
            description="List all QEMU virtual machines on a Proxmox node.",
            inputSchema={
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Proxmox node name"},
                },
                "required": ["node"],
            },
        ),
        types.Tool(
            name="get_vm_status",
            description=(
                "Get the current power state and resource usage of a specific QEMU VM."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Proxmox node name"},
                    "vmid": {"type": "integer", "description": "VM ID", "minimum": 100},
                },
                "required": ["node", "vmid"],
            },
        ),
        types.Tool(
            name="start_vm",
            description="Power on a stopped QEMU virtual machine. Returns the task UPID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Proxmox node name"},
                    "vmid": {"type": "integer", "description": "VM ID", "minimum": 100},
                },
                "required": ["node", "vmid"],
            },
        ),
        types.Tool(
            name="stop_vm",
            description=(
                "Force-stop a QEMU VM immediately (equivalent to pulling the power plug). "
                "Use shutdown_vm for a graceful ACPI shutdown. Returns the task UPID."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Proxmox node name"},
                    "vmid": {"type": "integer", "description": "VM ID", "minimum": 100},
                },
                "required": ["node", "vmid"],
            },
        ),
        types.Tool(
            name="shutdown_vm",
            description=(
                "Gracefully shut down a QEMU VM via ACPI. The VM OS is asked to "
                "power off cleanly. Returns the task UPID."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Proxmox node name"},
                    "vmid": {"type": "integer", "description": "VM ID", "minimum": 100},
                    "timeout": {
                        "type": "integer",
                        "description": "Seconds to wait before forcing shutdown (default 60)",
                        "minimum": 1,
                        "maximum": 600,
                    },
                },
                "required": ["node", "vmid"],
            },
        ),
        types.Tool(
            name="reboot_vm",
            description="Reboot a running QEMU VM. Returns the task UPID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Proxmox node name"},
                    "vmid": {"type": "integer", "description": "VM ID", "minimum": 100},
                },
                "required": ["node", "vmid"],
            },
        ),

        # ── LXC Containers ──────────────────────────────────────────────────
        types.Tool(
            name="list_lxc",
            description="List all LXC containers on a Proxmox node.",
            inputSchema={
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Proxmox node name"},
                },
                "required": ["node"],
            },
        ),
        types.Tool(
            name="get_lxc_status",
            description="Get the current power state and resource usage of a specific LXC container.",
            inputSchema={
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Proxmox node name"},
                    "vmid": {"type": "integer", "description": "Container ID", "minimum": 100},
                },
                "required": ["node", "vmid"],
            },
        ),
        types.Tool(
            name="start_lxc",
            description="Start a stopped LXC container. Returns the task UPID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Proxmox node name"},
                    "vmid": {"type": "integer", "description": "Container ID", "minimum": 100},
                },
                "required": ["node", "vmid"],
            },
        ),
        types.Tool(
            name="stop_lxc",
            description=(
                "Force-stop an LXC container immediately. "
                "Use shutdown_lxc for a graceful shutdown. Returns the task UPID."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Proxmox node name"},
                    "vmid": {"type": "integer", "description": "Container ID", "minimum": 100},
                },
                "required": ["node", "vmid"],
            },
        ),
        types.Tool(
            name="shutdown_lxc",
            description=(
                "Gracefully shut down an LXC container. Returns the task UPID."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Proxmox node name"},
                    "vmid": {"type": "integer", "description": "Container ID", "minimum": 100},
                    "timeout": {
                        "type": "integer",
                        "description": "Seconds to wait before forcing shutdown (default 60)",
                        "minimum": 1,
                        "maximum": 600,
                    },
                },
                "required": ["node", "vmid"],
            },
        ),

        # ── Storage ─────────────────────────────────────────────────────────
        types.Tool(
            name="list_storages",
            description="List all storage pools configured on a Proxmox node with usage statistics.",
            inputSchema={
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Proxmox node name"},
                },
                "required": ["node"],
            },
        ),
        types.Tool(
            name="get_storage_content",
            description=(
                "List content of a storage pool on a node: VM disk images, "
                "ISO images, container templates, and backups."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Proxmox node name"},
                    "storage": {"type": "string", "description": "Storage ID (e.g. 'local', 'local-lvm')"},
                },
                "required": ["node", "storage"],
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """Dispatch MCP tool calls to the appropriate Proxmox API handler."""
    log.info("tool.called", tool=name)

    try:
        settings = get_settings()
    except RuntimeError as e:
        return _err(f"Configuration error: {e}")

    try:
        async with ProxmoxClient(settings) as client:
            return await _dispatch(name, arguments, client)
    except ProxmoxAPIError as e:
        log.error("proxmox.api_error", tool=name, status=e.status_code, error=str(e))
        return _err(str(e))
    except ValidationError as e:
        log.warning("tool.validation_error", tool=name, errors=e.errors())
        return _err(f"Input validation error: {e}")
    except Exception as e:
        log.exception("tool.unexpected_error", tool=name)
        return _err(f"Unexpected error: {type(e).__name__}: {e}")


async def _dispatch(
    name: str,
    arguments: dict,
    client: ProxmoxClient,
) -> list[types.TextContent]:
    """Route tool name to implementation."""

    # ── health_check ────────────────────────────────────────────────────────
    if name == "health_check":
        version = await client.get_version()
        return _ok({"status": "ok", "proxmox": version})

    # ── get_cluster_status ──────────────────────────────────────────────────
    if name == "get_cluster_status":
        status = await client.get_cluster_status()
        return _ok(status)

    # ── list_tasks ──────────────────────────────────────────────────────────
    if name == "list_tasks":
        limit = int(arguments.get("limit", 50))
        limit = max(1, min(limit, 200))
        tasks = await client.list_tasks(limit=limit)
        # Summarise the most useful fields
        summary = [
            {
                "upid": t.get("upid"),
                "node": t.get("node"),
                "type": t.get("type"),
                "id": t.get("id"),
                "user": t.get("user"),
                "status": t.get("status"),
                "starttime": t.get("starttime"),
                "endtime": t.get("endtime"),
            }
            for t in tasks
        ]
        return _ok(summary)

    # ── list_nodes ──────────────────────────────────────────────────────────
    if name == "list_nodes":
        nodes = await client.list_nodes()
        summary = [
            {
                "node": n.get("node"),
                "status": n.get("status"),
                "uptime": n.get("uptime"),
                "cpu": round(n.get("cpu", 0) * 100, 1),  # fraction → %
                "maxcpu": n.get("maxcpu"),
                "mem_gb": round(n.get("mem", 0) / 1_073_741_824, 2),
                "maxmem_gb": round(n.get("maxmem", 0) / 1_073_741_824, 2),
                "disk_gb": round(n.get("disk", 0) / 1_073_741_824, 2),
                "maxdisk_gb": round(n.get("maxdisk", 0) / 1_073_741_824, 2),
                "level": n.get("level"),
            }
            for n in nodes
        ]
        return _ok(summary)

    # ── get_node_status ─────────────────────────────────────────────────────
    if name == "get_node_status":
        inp = NodeInput(**arguments)
        status = await client.get_node_status(inp.node)
        return _ok(status)

    # ── list_vms ────────────────────────────────────────────────────────────
    if name == "list_vms":
        inp = NodeInput(**arguments)
        vms = await client.list_vms(inp.node)
        summary = [
            {
                "vmid": v.get("vmid"),
                "name": v.get("name"),
                "status": v.get("status"),
                "uptime": v.get("uptime"),
                "cpu": round(v.get("cpu", 0) * 100, 1),
                "cpus": v.get("cpus"),
                "mem_mb": round(v.get("mem", 0) / 1_048_576, 0),
                "maxmem_mb": round(v.get("maxmem", 0) / 1_048_576, 0),
                "disk_gb": round(v.get("disk", 0) / 1_073_741_824, 2),
                "maxdisk_gb": round(v.get("maxdisk", 0) / 1_073_741_824, 2),
            }
            for v in vms
        ]
        return _ok(summary)

    # ── get_vm_status ────────────────────────────────────────────────────────
    if name == "get_vm_status":
        inp = VmInput(**arguments)
        status = await client.get_vm_status(inp.node, inp.vmid)
        return _ok(status)

    # ── start_vm ─────────────────────────────────────────────────────────────
    if name == "start_vm":
        inp = VmInput(**arguments)
        task = await client.start_vm(inp.node, inp.vmid)
        return _ok({"result": "start_requested", "node": inp.node, "vmid": inp.vmid, "task": task})

    # ── stop_vm ──────────────────────────────────────────────────────────────
    if name == "stop_vm":
        inp = VmInput(**arguments)
        task = await client.stop_vm(inp.node, inp.vmid)
        return _ok({"result": "stop_requested", "node": inp.node, "vmid": inp.vmid, "task": task})

    # ── shutdown_vm ───────────────────────────────────────────────────────────
    if name == "shutdown_vm":
        inp = ShutdownVmInput(**arguments)
        task = await client.shutdown_vm(inp.node, inp.vmid, timeout=inp.timeout or 60)
        return _ok({"result": "shutdown_requested", "node": inp.node, "vmid": inp.vmid, "task": task})

    # ── reboot_vm ─────────────────────────────────────────────────────────────
    if name == "reboot_vm":
        inp = VmInput(**arguments)
        task = await client.reboot_vm(inp.node, inp.vmid)
        return _ok({"result": "reboot_requested", "node": inp.node, "vmid": inp.vmid, "task": task})

    # ── list_lxc ─────────────────────────────────────────────────────────────
    if name == "list_lxc":
        inp = NodeInput(**arguments)
        containers = await client.list_lxc(inp.node)
        summary = [
            {
                "vmid": c.get("vmid"),
                "name": c.get("name"),
                "status": c.get("status"),
                "uptime": c.get("uptime"),
                "cpu": round(c.get("cpu", 0) * 100, 1),
                "cpus": c.get("cpus"),
                "mem_mb": round(c.get("mem", 0) / 1_048_576, 0),
                "maxmem_mb": round(c.get("maxmem", 0) / 1_048_576, 0),
                "disk_gb": round(c.get("disk", 0) / 1_073_741_824, 2),
                "maxdisk_gb": round(c.get("maxdisk", 0) / 1_073_741_824, 2),
            }
            for c in containers
        ]
        return _ok(summary)

    # ── get_lxc_status ────────────────────────────────────────────────────────
    if name == "get_lxc_status":
        inp = VmInput(**arguments)
        status = await client.get_lxc_status(inp.node, inp.vmid)
        return _ok(status)

    # ── start_lxc ────────────────────────────────────────────────────────────
    if name == "start_lxc":
        inp = VmInput(**arguments)
        task = await client.start_lxc(inp.node, inp.vmid)
        return _ok({"result": "start_requested", "node": inp.node, "vmid": inp.vmid, "task": task})

    # ── stop_lxc ─────────────────────────────────────────────────────────────
    if name == "stop_lxc":
        inp = VmInput(**arguments)
        task = await client.stop_lxc(inp.node, inp.vmid)
        return _ok({"result": "stop_requested", "node": inp.node, "vmid": inp.vmid, "task": task})

    # ── shutdown_lxc ─────────────────────────────────────────────────────────
    if name == "shutdown_lxc":
        inp = ShutdownVmInput(**arguments)
        task = await client.shutdown_lxc(inp.node, inp.vmid, timeout=inp.timeout or 60)
        return _ok({"result": "shutdown_requested", "node": inp.node, "vmid": inp.vmid, "task": task})

    # ── list_storages ────────────────────────────────────────────────────────
    if name == "list_storages":
        inp = NodeInput(**arguments)
        storages = await client.list_storages(inp.node)
        summary = [
            {
                "storage": s.get("storage"),
                "type": s.get("type"),
                "status": s.get("status"),
                "active": s.get("active"),
                "enabled": s.get("enabled"),
                "used_gb": round(s.get("used", 0) / 1_073_741_824, 2),
                "avail_gb": round(s.get("avail", 0) / 1_073_741_824, 2),
                "total_gb": round(s.get("total", 0) / 1_073_741_824, 2),
                "content": s.get("content"),
            }
            for s in storages
        ]
        return _ok(summary)

    # ── get_storage_content ───────────────────────────────────────────────────
    if name == "get_storage_content":
        inp = StorageInput(**arguments)
        items = await client.get_storage_content(inp.node, inp.storage)
        summary = [
            {
                "volid": i.get("volid"),
                "content": i.get("content"),
                "format": i.get("format"),
                "size_gb": round(i.get("size", 0) / 1_073_741_824, 2),
                "vmid": i.get("vmid"),
                "notes": i.get("notes"),
            }
            for i in items
        ]
        return _ok(summary)

    return _err(f"Unknown tool: {name!r}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _serve() -> None:
    log.info("server.starting", name="proxmox-mcp")
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main() -> None:
    import asyncio
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
