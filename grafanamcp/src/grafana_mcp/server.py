"""
Grafana MCP Server.

Tools:
  1.  health_check       — verify connectivity and token validity
  2.  list_dashboards    — search dashboards (by query / folder)
  3.  get_dashboard      — fetch full dashboard JSON by UID
  4.  create_dashboard   — create (or update) a dashboard from JSON
  5.  list_datasources   — list all configured data sources
  6.  list_folders       — list dashboard folders
  7.  list_alerts        — list provisioning alert rules
  8.  list_annotations   — query annotations (by time range / dashboard)
  9.  list_users         — list Grafana users (admin token required)

Run:
    python -m grafana_mcp.server
    # or via the installed script:
    grafana-mcp
"""
from __future__ import annotations

import asyncio
import json
import mcp.server.stdio
from mcp.server import Server
from mcp.types import Tool, TextContent

from grafana_mcp.config import get_settings
from grafana_mcp.client import GrafanaClient

app = Server("grafana-mcp")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="health_check",
            description="Validate Grafana connectivity and API token validity. Returns Grafana version and database status.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="list_dashboards",
            description="Search and list dashboards. Optionally filter by a search query string or folder UID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search string to filter dashboards by title."},
                    "folder_uid": {"type": "string", "description": "Limit results to a specific folder UID."},
                    "limit": {"type": "integer", "description": "Maximum number of results (default 100).", "default": 100},
                },
                "required": [],
            },
        ),
        Tool(
            name="get_dashboard",
            description="Fetch the full JSON model of a dashboard by its UID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "uid": {"type": "string", "description": "Dashboard UID (visible in the dashboard URL)."},
                },
                "required": ["uid"],
            },
        ),
        Tool(
            name="create_dashboard",
            description=(
                "Create a new dashboard (or update an existing one) on Grafana. "
                "Provide a complete Grafana dashboard JSON object as `dashboard_json`. "
                "The JSON must have at minimum `title` and `panels`. "
                "Set `overwrite` to true to update an existing dashboard by UID. "
                "Optionally specify a `folder_uid` to place the dashboard in a folder."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "dashboard_json": {
                        "type": "string",
                        "description": "JSON string of the Grafana dashboard model (must include title and panels).",
                    },
                    "folder_uid": {
                        "type": "string",
                        "description": "UID of the folder to store the dashboard in. Defaults to General (root).",
                    },
                    "message": {
                        "type": "string",
                        "description": "Commit message / change description.",
                        "default": "Created via Grafana MCP",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "If true, overwrite an existing dashboard with the same UID.",
                        "default": False,
                    },
                },
                "required": ["dashboard_json"],
            },
        ),
        Tool(
            name="list_datasources",
            description="List all data sources configured in Grafana.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="list_folders",
            description="List all dashboard folders.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Maximum number of folders to return (default 100).", "default": 100},
                },
                "required": [],
            },
        ),
        Tool(
            name="list_alerts",
            description="List all provisioning alert rules.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="list_annotations",
            description="Query Grafana annotations. Optionally filter by time range or dashboard ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "from_ms": {"type": "integer", "description": "Start of time range in milliseconds epoch."},
                    "to_ms": {"type": "integer", "description": "End of time range in milliseconds epoch."},
                    "dashboard_id": {"type": "integer", "description": "Limit annotations to a specific dashboard ID."},
                    "limit": {"type": "integer", "description": "Max number of annotations to return (default 100).", "default": 100},
                },
                "required": [],
            },
        ),
        Tool(
            name="list_users",
            description="List Grafana users. Requires an admin-level API token.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Filter users by login, email or name."},
                    "page": {"type": "integer", "description": "Page number (default 1).", "default": 1},
                    "perpage": {"type": "integer", "description": "Results per page (default 50).", "default": 50},
                },
                "required": [],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    client = GrafanaClient()

    if name == "health_check":
        data = await client.get("health")
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    if name == "list_dashboards":
        params: dict[str, str] = {"type": "dash-db"}
        if arguments.get("query"):
            params["query"] = arguments["query"]
        if arguments.get("folder_uid"):
            params["folderUIDs"] = arguments["folder_uid"]
        if arguments.get("limit"):
            params["limit"] = str(arguments["limit"])
        data = await client.get("search", **params)
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    if name == "get_dashboard":
        uid = arguments["uid"]
        data = await client.get(f"dashboards/uid/{uid}")
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    if name == "create_dashboard":
        dashboard = json.loads(arguments["dashboard_json"])
        # Ensure sane defaults for new dashboards
        dashboard.setdefault("schemaVersion", 38)
        dashboard.setdefault("version", 0)
        dashboard.setdefault("timezone", "browser")
        dashboard.setdefault("panels", [])
        body: dict = {
            "dashboard": dashboard,
            "message": arguments.get("message", "Created via Grafana MCP"),
            "overwrite": arguments.get("overwrite", False),
        }
        if arguments.get("folder_uid"):
            body["folderUid"] = arguments["folder_uid"]
        data = await client.post("dashboards/db", body)
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    if name == "list_datasources":
        data = await client.get("datasources")
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    if name == "list_folders":
        limit = arguments.get("limit", 100)
        data = await client.get("folders", limit=str(limit))
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    if name == "list_alerts":
        data = await client.get("v1/provisioning/alert-rules")
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    if name == "list_annotations":
        params = {}
        if arguments.get("from_ms"):
            params["from"] = str(arguments["from_ms"])
        if arguments.get("to_ms"):
            params["to"] = str(arguments["to_ms"])
        if arguments.get("dashboard_id"):
            params["dashboardId"] = str(arguments["dashboard_id"])
        params["limit"] = str(arguments.get("limit", 100))
        data = await client.get("annotations", **params)
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    if name == "list_users":
        params = {"page": str(arguments.get("page", 1)), "perpage": str(arguments.get("perpage", 50))}
        if arguments.get("query"):
            params["query"] = arguments["query"]
        data = await client.get("users", **params)
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    raise ValueError(f"Unknown tool: {name}")


def main() -> None:
    cfg = get_settings()
    import structlog
    log = structlog.get_logger(__name__)
    log.info("grafana_mcp.starting", url=cfg.grafana_url)
    asyncio.run(mcp.server.stdio.stdio_server(app))


if __name__ == "__main__":
    main()
