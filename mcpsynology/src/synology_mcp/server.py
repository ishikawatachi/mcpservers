"""
Synology DSM MCP Server — main entry point.

Exposes the following MCP tools:

  Read / Introspection
  ─────────────────────
  1.  health_check            — validate connectivity and PAT validity
  2.  get_system_info         — model, firmware, serial number, uptime, hostname
  3.  get_system_utilization  — CPU %, RAM, per-interface network I/O, disk I/O
  4.  get_storage_info        — volumes, RAID groups, storage pool health
  5.  get_disk_info           — per-disk S.M.A.R.T. status, temperature, model

  Shares & Files
  ───────────────
  6.  list_shares             — all shared folders with quota and encryption status
  7.  list_files              — browse files in a shared folder path

  Packages & Tasks
  ─────────────────
  8.  list_packages           — installed packages and running status
  9.  list_scheduled_tasks    — Task Scheduler jobs and last-run results

  Container Manager (Docker)
  ──────────────────────────
  10. list_docker_containers  — containers managed by Container Manager
  11. list_docker_images      — Docker images stored on the NAS

  Security & Backup
  ──────────────────
  12. get_security_status     — Security Advisor scan results
  13. get_backup_tasks        — Hyper Backup task status and last-run results

Run:
    python -m synology_mcp.server
    # or via the installed script:
    synology-mcp
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

from synology_mcp.client import SynologyAPIError, SynologyClient
from synology_mcp.config import get_settings
from synology_mcp.models import ListFilesInput

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

app = Server("synology-mcp")


def _ok(data: object) -> list[types.TextContent]:
    """Wrap a result as a JSON TextContent response."""
    return [types.TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


def _err(message: str) -> list[types.TextContent]:
    """Wrap an error string as a TextContent response."""
    return [types.TextContent(type="text", text=json.dumps({"error": message}))]


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="health_check",
            description=(
                "Validate Synology DSM connectivity and Personal Access Token (PAT) validity. "
                "Returns DSM version and a list of available APIs."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="get_system_info",
            description=(
                "Return DSM system information: NAS model, firmware version, serial number, "
                "temperature, uptime, hostname, and RAM."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="get_system_utilization",
            description=(
                "Return current system resource utilization: CPU usage %, total/used/free RAM, "
                "per-network-interface TX/RX bytes, and disk I/O read/write bytes."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="get_storage_info",
            description=(
                "Return storage overview: RAID groups, volumes (size, used, free, filesystem), "
                "and disk health summary (normal, warning, error counts)."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="get_disk_info",
            description=(
                "Return per-disk details for all drives installed in the NAS: model, "
                "firmware, serial, temperature, S.M.A.R.T. status, and slot location."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="list_shares",
            description=(
                "Return all shared folders: name, path, comment, whether encryption is active, "
                "recycle bin status, and disk quota if set."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="list_files",
            description=(
                "Browse files and subfolders inside a Synology shared folder. "
                "Returns name, type (dir/file), size, owner, and modification time."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "folder_path": {
                        "type": "string",
                        "description": (
                            "Absolute path starting with '/' — use the share name as the first "
                            "component, e.g. '/docker', '/homes/admin', '/photo/2024'."
                        ),
                    },
                    "additional": {
                        "type": "string",
                        "description": (
                            "Optional comma-separated extra fields to include in the response. "
                            "Supported: real_path, size, owner, time, perm, type"
                        ),
                    },
                },
                "required": ["folder_path"],
            },
        ),
        types.Tool(
            name="list_packages",
            description=(
                "Return all packages installed via Package Center: ID, display name, version, "
                "author, and whether the package is currently running."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="list_scheduled_tasks",
            description=(
                "Return all Task Scheduler jobs: name, type (script/package), owner, "
                "schedule (cron expression), enabled status, and last-run result."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="list_docker_containers",
            description=(
                "Return all Docker containers managed by Container Manager (formerly Docker "
                "package): name, image, status (running/stopped), ports, and creation time."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="list_docker_images",
            description=(
                "Return all Docker images stored on the NAS: tag, size, creation time, "
                "and whether any containers are using the image."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="get_security_status",
            description=(
                "Return Security Advisor scan results: overall risk score, last scan time, "
                "and individual check results (pass/warn/fail) for firewall, updates, "
                "SSH config, account policies, and more."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="get_backup_tasks",
            description=(
                "Return all Hyper Backup tasks: name, destination type, last backup time, "
                "last backup result (success/error/warning), and schedule."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
    ]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

@app.call_tool()
async def call_tool(
    name: str,
    arguments: dict,  # type: ignore[type-arg]
) -> list[types.TextContent]:
    settings = get_settings()
    try:
        async with SynologyClient(settings) as client:
            # ── Read / Introspection ───────────────────────────────────────
            if name == "health_check":
                data = await client.query_api_info()
                # Summarise the available API count — data may be a dict of api_name → info
                api_count = len(data) if isinstance(data, dict) else "unknown"
                return _ok({
                    "status": "ok",
                    "synology_url": settings.synology_url,
                    "available_apis": api_count,
                    "note": "PAT is valid and DSM is reachable.",
                })

            elif name == "get_system_info":
                return _ok(await client.get_dsm_info())

            elif name == "get_system_utilization":
                return _ok(await client.get_system_utilization())

            elif name == "get_storage_info":
                return _ok(await client.get_storage_info())

            elif name == "get_disk_info":
                return _ok(await client.get_disk_info())

            # ── Shares & Files ────────────────────────────────────────────
            elif name == "list_shares":
                return _ok(await client.list_shares())

            elif name == "list_files":
                try:
                    inp = ListFilesInput(**arguments)
                except (ValidationError, TypeError) as exc:
                    return _err(f"Invalid input: {exc}")
                return _ok(await client.list_files(
                    folder_path=inp.folder_path,
                    additional=inp.additional,
                ))

            # ── Packages & Tasks ──────────────────────────────────────────
            elif name == "list_packages":
                return _ok(await client.list_packages())

            elif name == "list_scheduled_tasks":
                return _ok(await client.list_scheduled_tasks())

            # ── Container Manager (Docker) ─────────────────────────────────
            elif name == "list_docker_containers":
                return _ok(await client.list_docker_containers())

            elif name == "list_docker_images":
                return _ok(await client.list_docker_images())

            # ── Security & Backup ─────────────────────────────────────────
            elif name == "get_security_status":
                return _ok(await client.get_security_status())

            elif name == "get_backup_tasks":
                return _ok(await client.get_backup_tasks())

            else:
                return _err(f"Unknown tool: {name!r}")

    except SynologyAPIError as exc:
        log.error("synology.api_error", tool=name, error=str(exc))
        return _err(str(exc))
    except Exception as exc:
        log.exception("synology.unexpected_error", tool=name)
        return _err(f"Unexpected error: {exc}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Start the MCP server over stdio."""
    import asyncio

    log.info("synology_mcp.starting", version="0.1.0")
    try:
        settings = get_settings()
        log.info("synology_mcp.config_ok", url=settings.synology_url)
    except RuntimeError as exc:
        log.error("synology_mcp.config_error", error=str(exc))
        sys.exit(1)

    async def _serve() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

    asyncio.run(_serve())


if __name__ == "__main__":
    main()
