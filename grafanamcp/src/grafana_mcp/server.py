"""
Grafana MCP Server — main entry point (stub).

Planned tools:
  1.  health_check       — verify connectivity and token validity  (GET /api/health)
  2.  list_dashboards    — search dashboards                       (GET /api/search?type=dash-db)
  3.  get_dashboard      — fetch dashboard JSON by UID             (GET /api/dashboards/uid/<uid>)
  4.  list_datasources   — list all data sources                   (GET /api/datasources)
  5.  list_alerts        — list alert rules                        (GET /api/v1/provisioning/alert-rules)
  6.  list_annotations   — query annotations                       (GET /api/annotations)
  7.  list_folders       — list dashboard folders                  (GET /api/folders)
  8.  list_users         — list users (admin token required)       (GET /api/users)

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
            description="Validate Grafana connectivity and API token.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        # TODO: add remaining tools here
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    client = GrafanaClient()

    if name == "health_check":
        data = await client.get("health")
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
