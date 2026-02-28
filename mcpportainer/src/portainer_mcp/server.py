"""
Portainer MCP Server — main entry point.

Exposes the following MCP tools:
  1.  list_endpoints        — list Portainer environments
  2.  list_containers       — list containers on an endpoint
  3.  inspect_container     — get full container details
  4.  start_container       — start a stopped container
  5.  stop_container        — stop a running container
  6.  container_logs        — retrieve container log output
  7.  list_images           — list Docker images on an endpoint
  8.  list_stacks           — list all deployed stacks
  9.  deploy_stack          — create or update a Compose stack
  10. health_check          — validate connectivity and token validity

Run:
    python -m portainer_mcp.server
    # or via the installed script:
    portainer-mcp
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

from portainer_mcp.client import PortainerAPIError, PortainerClient
from portainer_mcp.config import get_settings
from portainer_mcp.models import (
    ContainerInput,
    ContainerLogsInput,
    DeployStackInput,
    EndpointIdInput,
)

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

app = Server("portainer-mcp")


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
        types.Tool(
            name="list_endpoints",
            description="List all Portainer environments (endpoints) with their IDs, names, and status.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="list_containers",
            description="List all Docker containers (running and stopped) on a Portainer endpoint.",
            inputSchema={
                "type": "object",
                "properties": {
                    "endpoint_id": {"type": "integer", "description": "Portainer endpoint ID", "minimum": 1},
                },
                "required": ["endpoint_id"],
            },
        ),
        types.Tool(
            name="inspect_container",
            description="Return full inspection details for a specific container.",
            inputSchema={
                "type": "object",
                "properties": {
                    "endpoint_id": {"type": "integer", "description": "Portainer endpoint ID", "minimum": 1},
                    "container_id": {"type": "string", "description": "Container ID or name"},
                },
                "required": ["endpoint_id", "container_id"],
            },
        ),
        types.Tool(
            name="start_container",
            description="Start a stopped Docker container.",
            inputSchema={
                "type": "object",
                "properties": {
                    "endpoint_id": {"type": "integer", "description": "Portainer endpoint ID", "minimum": 1},
                    "container_id": {"type": "string", "description": "Container ID or name"},
                },
                "required": ["endpoint_id", "container_id"],
            },
        ),
        types.Tool(
            name="stop_container",
            description="Stop a running Docker container.",
            inputSchema={
                "type": "object",
                "properties": {
                    "endpoint_id": {"type": "integer", "description": "Portainer endpoint ID", "minimum": 1},
                    "container_id": {"type": "string", "description": "Container ID or name"},
                },
                "required": ["endpoint_id", "container_id"],
            },
        ),
        types.Tool(
            name="container_logs",
            description="Retrieve stdout/stderr logs from a Docker container.",
            inputSchema={
                "type": "object",
                "properties": {
                    "endpoint_id": {"type": "integer", "description": "Portainer endpoint ID", "minimum": 1},
                    "container_id": {"type": "string", "description": "Container ID or name"},
                    "tail": {"type": "integer", "description": "Number of log lines to return (default 100, max 5000)", "minimum": 1, "maximum": 5000},
                    "timestamps": {"type": "boolean", "description": "Include timestamps"},
                },
                "required": ["endpoint_id", "container_id"],
            },
        ),
        types.Tool(
            name="list_images",
            description="List all Docker images on a Portainer endpoint.",
            inputSchema={
                "type": "object",
                "properties": {
                    "endpoint_id": {"type": "integer", "description": "Portainer endpoint ID", "minimum": 1},
                },
                "required": ["endpoint_id"],
            },
        ),
        types.Tool(
            name="list_stacks",
            description="List all Docker stacks managed by Portainer.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="deploy_stack",
            description=(
                "Deploy a new Docker Compose stack or update an existing one. "
                "Provide the full Compose YAML as compose_content."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "endpoint_id": {"type": "integer", "description": "Portainer endpoint ID", "minimum": 1},
                    "stack_name": {"type": "string", "description": "Stack name (alphanumeric, hyphens, underscores)"},
                    "compose_content": {"type": "string", "description": "Docker Compose YAML content"},
                    "env_vars": {
                        "type": "object",
                        "description": "Optional environment variables for the stack",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["endpoint_id", "stack_name", "compose_content"],
            },
        ),
        types.Tool(
            name="health_check",
            description="Validate Portainer connectivity and API token validity without triggering any operations.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
    ]


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """Dispatch MCP tool calls to the appropriate Portainer API handler."""
    log.info("tool.called", tool=name)

    try:
        settings = get_settings()
    except RuntimeError as e:
        return _err(f"Configuration error: {e}")

    try:
        async with PortainerClient(settings) as client:
            return await _dispatch(name, arguments, client)
    except PortainerAPIError as e:
        log.error("portainer.api_error", tool=name, status=e.status_code, error=str(e))
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
    client: PortainerClient,
) -> list[types.TextContent]:
    """Route tool name to implementation."""

    # --- health_check ---
    if name == "health_check":
        status = await client.health()
        return _ok({"status": "ok", "portainer": status})

    # --- list_endpoints ---
    if name == "list_endpoints":
        endpoints = await client.list_endpoints()
        summary = [
            {"id": e.get("Id"), "name": e.get("Name"), "url": e.get("URL"), "status": e.get("Status")}
            for e in endpoints
        ]
        return _ok(summary)

    # --- list_stacks ---
    if name == "list_stacks":
        stacks = await client.list_stacks()
        summary = [
            {"id": s.get("Id"), "name": s.get("Name"), "endpoint_id": s.get("EndpointId"), "status": s.get("Status")}
            for s in stacks
        ]
        return _ok(summary)

    # --- list_containers ---
    if name == "list_containers":
        inp = EndpointIdInput(**arguments)
        containers = await client.list_containers(inp.endpoint_id)
        summary = [
            {
                "id": c.get("Id", "")[:12],
                "names": c.get("Names", []),
                "image": c.get("Image", ""),
                "state": c.get("State", ""),
                "status": c.get("Status", ""),
            }
            for c in containers
        ]
        return _ok(summary)

    # --- inspect_container ---
    if name == "inspect_container":
        inp = ContainerInput(**arguments)
        detail = await client.inspect_container(inp.endpoint_id, inp.container_id)
        return _ok(detail)

    # --- start_container ---
    if name == "start_container":
        inp = ContainerInput(**arguments)
        await client.start_container(inp.endpoint_id, inp.container_id)
        return _ok({"result": "started", "container_id": inp.container_id})

    # --- stop_container ---
    if name == "stop_container":
        inp = ContainerInput(**arguments)
        await client.stop_container(inp.endpoint_id, inp.container_id)
        return _ok({"result": "stopped", "container_id": inp.container_id})

    # --- container_logs ---
    if name == "container_logs":
        inp = ContainerLogsInput(**arguments)
        logs = await client.container_logs(
            inp.endpoint_id,
            inp.container_id,
            tail=inp.tail,
            timestamps=inp.timestamps,
        )
        return _ok({"logs": logs})

    # --- list_images ---
    if name == "list_images":
        inp = EndpointIdInput(**arguments)
        images = await client.list_images(inp.endpoint_id)
        summary = [
            {
                "id": img.get("Id", "")[:19],
                "tags": img.get("RepoTags", []),
                "size_mb": round(img.get("Size", 0) / 1_048_576, 1),
                "created": img.get("Created"),
            }
            for img in images
        ]
        return _ok(summary)

    # --- deploy_stack ---
    if name == "deploy_stack":
        inp = DeployStackInput(**arguments)
        result = await client.deploy_stack(
            inp.endpoint_id,
            inp.stack_name,
            inp.compose_content,
            inp.env_vars,
        )
        return _ok({"result": "deployed", "stack": result})

    return _err(f"Unknown tool: {name!r}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _serve() -> None:
    log.info("server.starting", name="portainer-mcp")
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main() -> None:
    import asyncio
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
