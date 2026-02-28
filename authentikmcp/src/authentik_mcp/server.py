"""
Authentik MCP Server — main entry point (stub).

Planned tools:
  1.  health_check        — verify connectivity and token    (GET /api/v3/root/config/)
  2.  list_users          — list all users                   (GET /api/v3/core/users/)
  3.  get_user            — fetch a user by pk               (GET /api/v3/core/users/<pk>/)
  4.  list_groups         — list all groups                  (GET /api/v3/core/groups/)
  5.  list_applications   — list all applications            (GET /api/v3/core/applications/)
  6.  list_flows          — list authentication flows        (GET /api/v3/flows/instances/)
  7.  list_providers      — list OAuth2/SAML/LDAP providers  (GET /api/v3/providers/all/)
  8.  list_tokens         — list API tokens (admin)          (GET /api/v3/core/tokens/)

Run:
    python -m authentik_mcp.server
    # or via the installed script:
    authentik-mcp
"""
from __future__ import annotations

import asyncio
import json
import mcp.server.stdio
from mcp.server import Server
from mcp.types import Tool, TextContent

from authentik_mcp.config import get_settings
from authentik_mcp.client import AuthentikClient

app = Server("authentik-mcp")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="health_check",
            description="Validate Authentik connectivity and API token.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        # TODO: add remaining tools here
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    client = AuthentikClient()

    if name == "health_check":
        data = await client.get("root/config/")
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    raise ValueError(f"Unknown tool: {name}")


def main() -> None:
    cfg = get_settings()
    import structlog
    log = structlog.get_logger(__name__)
    log.info("authentik_mcp.starting", url=cfg.authentik_url)
    asyncio.run(mcp.server.stdio.stdio_server(app))


if __name__ == "__main__":
    main()
