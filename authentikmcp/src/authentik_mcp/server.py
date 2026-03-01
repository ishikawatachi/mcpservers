"""
Authentik MCP Server.

Tools:
  1.  health_check          — verify connectivity and token
  2.  list_users            — list all users (with optional search)
  3.  create_user           — create a new user account
  4.  list_groups           — list all groups
  5.  list_applications     — list all applications
  6.  create_application    — create a new application
  7.  list_providers        — list all providers (OAuth2/SAML/LDAP/Proxy)
  8.  create_oauth2_provider — create an OAuth2 / OpenID Connect provider
  9.  list_flows            — list authentication/enrollment flows
  10. list_sources          — list identity sources (federations / social logins)
  11. create_oauth_source   — add a new OAuth federation source (Google, GitHub, etc.)

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
            description="Validate Authentik connectivity and API token. Returns server configuration.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="list_users",
            description="List Authentik users. Optionally filter by username, name or email.",
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {"type": "string", "description": "Search term — matches username, name or email."},
                    "page": {"type": "integer", "description": "Page number (default 1).", "default": 1},
                    "page_size": {"type": "integer", "description": "Results per page (default 20).", "default": 20},
                },
                "required": [],
            },
        ),
        Tool(
            name="create_user",
            description=(
                "Create a new Authentik user account. "
                "`username` and `name` are required. Email and password are optional. "
                "The user is active by default."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "Unique login username."},
                    "name": {"type": "string", "description": "Full display name."},
                    "email": {"type": "string", "description": "Email address (optional)."},
                    "password": {"type": "string", "description": "Initial password. If omitted, user must reset."},
                    "is_active": {"type": "boolean", "description": "Whether the account is active (default true).", "default": True},
                    "groups": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of group PKs to add the user to (optional).",
                    },
                },
                "required": ["username", "name"],
            },
        ),
        Tool(
            name="list_groups",
            description="List Authentik groups. Optionally filter by name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {"type": "string", "description": "Filter groups by name."},
                    "page": {"type": "integer", "default": 1},
                    "page_size": {"type": "integer", "default": 20},
                },
                "required": [],
            },
        ),
        Tool(
            name="list_applications",
            description="List all Authentik applications.",
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {"type": "string", "description": "Filter by application name or slug."},
                    "page": {"type": "integer", "default": 1},
                    "page_size": {"type": "integer", "default": 20},
                },
                "required": [],
            },
        ),
        Tool(
            name="create_application",
            description=(
                "Create a new Authentik application. "
                "An application can optionally be linked to an existing provider by its PK. "
                "Use list_providers to find available provider PKs."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Human-readable application name."},
                    "slug": {"type": "string", "description": "URL-safe unique identifier (lowercase, hyphens)."},
                    "provider": {"type": "integer", "description": "PK of the provider to attach (optional)."},
                    "meta_launch_url": {"type": "string", "description": "URL users are sent to when launching the app (optional)."},
                    "meta_description": {"type": "string", "description": "Short description shown in the app library (optional)."},
                    "meta_publisher": {"type": "string", "description": "Publisher / vendor name (optional)."},
                    "open_in_new_tab": {"type": "boolean", "description": "Open launch URL in a new tab (default false).", "default": False},
                },
                "required": ["name", "slug"],
            },
        ),
        Tool(
            name="list_providers",
            description="List all Authentik providers (OAuth2, SAML, LDAP, Proxy, RADIUS, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {"type": "string", "description": "Filter by provider name."},
                    "page": {"type": "integer", "default": 1},
                    "page_size": {"type": "integer", "default": 20},
                },
                "required": [],
            },
        ),
        Tool(
            name="create_oauth2_provider",
            description=(
                "Create a new OAuth2 / OpenID Connect provider in Authentik. "
                "Use list_flows to find the `authorization_flow` slug. "
                "`redirect_uris` is a newline-separated list of allowed callback URIs. "
                "Returns the new provider including its auto-generated client_id and client_secret."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Provider name (shown in admin UI)."},
                    "authorization_flow": {
                        "type": "string",
                        "description": "Slug of the authorization flow (e.g. 'default-provider-authorization-implicit-consent').",
                    },
                    "client_type": {
                        "type": "string",
                        "enum": ["confidential", "public"],
                        "description": "OAuth2 client type. Use 'confidential' for server-side apps, 'public' for SPAs/mobile.",
                        "default": "confidential",
                    },
                    "redirect_uris": {
                        "type": "string",
                        "description": "Newline-separated list of allowed redirect URIs.",
                    },
                    "sub_mode": {
                        "type": "string",
                        "enum": ["hashed_user_id", "user_id", "user_uuid", "user_username", "user_email", "user_upn"],
                        "description": "What to use as the OIDC 'sub' claim (default: hashed_user_id).",
                        "default": "hashed_user_id",
                    },
                    "access_code_validity": {
                        "type": "string",
                        "description": "Access code validity duration (default 'minutes=1').",
                        "default": "minutes=1",
                    },
                    "access_token_validity": {
                        "type": "string",
                        "description": "Access token validity duration (default 'minutes=5').",
                        "default": "minutes=5",
                    },
                    "refresh_token_validity": {
                        "type": "string",
                        "description": "Refresh token validity duration (default 'days=30').",
                        "default": "days=30",
                    },
                    "include_claims_in_id_token": {
                        "type": "boolean",
                        "description": "Embed user claims in the ID token (default true).",
                        "default": True,
                    },
                },
                "required": ["name", "authorization_flow", "redirect_uris"],
            },
        ),
        Tool(
            name="list_flows",
            description="List Authentik flows. Optionally filter by designation (authentication, authorization, enrollment, invalidation, recovery, unenrollment, stage_configuration).",
            inputSchema={
                "type": "object",
                "properties": {
                    "designation": {
                        "type": "string",
                        "description": "Filter by flow designation.",
                        "enum": [
                            "authentication",
                            "authorization",
                            "enrollment",
                            "invalidation",
                            "recovery",
                            "unenrollment",
                            "stage_configuration",
                        ],
                    },
                    "search": {"type": "string", "description": "Filter by flow name or slug."},
                    "page": {"type": "integer", "default": 1},
                    "page_size": {"type": "integer", "default": 20},
                },
                "required": [],
            },
        ),
        Tool(
            name="list_sources",
            description="List identity federation sources (social logins, LDAP, SAML IdPs, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {"type": "string", "description": "Filter by source name or slug."},
                    "page": {"type": "integer", "default": 1},
                    "page_size": {"type": "integer", "default": 20},
                },
                "required": [],
            },
        ),
        Tool(
            name="create_oauth_source",
            description=(
                "Create a new OAuth / social login federation source (e.g. Google, GitHub, Discord, Azure AD, Okta). "
                "Use list_flows to find authentication_flow and enrollment_flow slugs. "
                "provider_type must be one of the supported Authentik OAuth source types."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Human-readable name for the federation source."},
                    "slug": {"type": "string", "description": "URL-safe identifier used in login URLs."},
                    "provider_type": {
                        "type": "string",
                        "description": "OAuth provider type. Common values: 'google', 'github', 'discord', 'azure-ad', 'okta', 'twitter', 'facebook', 'gitlab', 'reddit', 'twitch'.",
                    },
                    "consumer_key": {"type": "string", "description": "OAuth Client ID / App ID from the identity provider."},
                    "consumer_secret": {"type": "string", "description": "OAuth Client Secret from the identity provider."},
                    "authentication_flow": {
                        "type": "string",
                        "description": "Slug of the flow used when an existing user logs in via this source (optional).",
                    },
                    "enrollment_flow": {
                        "type": "string",
                        "description": "Slug of the flow used when a new user registers via this source (optional).",
                    },
                    "access_token_url": {"type": "string", "description": "Override the access token URL (for custom/Okta providers)."},
                    "authorization_url": {"type": "string", "description": "Override the authorization URL (for custom/Okta providers)."},
                    "profile_url": {"type": "string", "description": "Override the user profile URL (for custom/Okta providers)."},
                    "oidc_jwks_url": {"type": "string", "description": "OIDC JWKS endpoint URL (for OIDC-compatible providers)."},
                    "additional_scopes": {"type": "string", "description": "Space-separated extra OAuth scopes to request (optional)."},
                    "enabled": {"type": "boolean", "description": "Enable this source immediately (default true).", "default": True},
                    "user_matching_mode": {
                        "type": "string",
                        "enum": ["identifier", "email_link", "email_deny", "username_link", "username_deny"],
                        "description": "How to match incoming users to existing Authentik accounts (default: identifier).",
                        "default": "identifier",
                    },
                },
                "required": ["name", "slug", "provider_type", "consumer_key", "consumer_secret"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    client = AuthentikClient()

    if name == "health_check":
        data = await client.get("root/config/")
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    if name == "list_users":
        params: dict[str, str] = {
            "page": str(arguments.get("page", 1)),
            "page_size": str(arguments.get("page_size", 20)),
        }
        if arguments.get("search"):
            params["search"] = arguments["search"]
        data = await client.get("core/users/", **params)
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    if name == "create_user":
        body: dict = {
            "username": arguments["username"],
            "name": arguments["name"],
            "is_active": arguments.get("is_active", True),
            "type": "internal",
        }
        if arguments.get("email"):
            body["email"] = arguments["email"]
        if arguments.get("groups"):
            body["groups"] = arguments["groups"]
        data = await client.post("core/users/", body)
        # Optionally set password if provided
        if arguments.get("password") and data.get("pk"):
            await client.post(f"core/users/{data['pk']}/set_password/", {"password": arguments["password"]})
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    if name == "list_groups":
        params = {
            "page": str(arguments.get("page", 1)),
            "page_size": str(arguments.get("page_size", 20)),
        }
        if arguments.get("search"):
            params["search"] = arguments["search"]
        data = await client.get("core/groups/", **params)
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    if name == "list_applications":
        params = {
            "page": str(arguments.get("page", 1)),
            "page_size": str(arguments.get("page_size", 20)),
        }
        if arguments.get("search"):
            params["search"] = arguments["search"]
        data = await client.get("core/applications/", **params)
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    if name == "create_application":
        body = {
            "name": arguments["name"],
            "slug": arguments["slug"],
            "open_in_new_tab": arguments.get("open_in_new_tab", False),
        }
        if arguments.get("provider") is not None:
            body["provider"] = arguments["provider"]
        if arguments.get("meta_launch_url"):
            body["meta_launch_url"] = arguments["meta_launch_url"]
        if arguments.get("meta_description"):
            body["meta_description"] = arguments["meta_description"]
        if arguments.get("meta_publisher"):
            body["meta_publisher"] = arguments["meta_publisher"]
        data = await client.post("core/applications/", body)
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    if name == "list_providers":
        params = {
            "page": str(arguments.get("page", 1)),
            "page_size": str(arguments.get("page_size", 20)),
        }
        if arguments.get("search"):
            params["search"] = arguments["search"]
        data = await client.get("providers/all/", **params)
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    if name == "create_oauth2_provider":
        body = {
            "name": arguments["name"],
            "authorization_flow": arguments["authorization_flow"],
            "client_type": arguments.get("client_type", "confidential"),
            "redirect_uris": arguments["redirect_uris"],
            "sub_mode": arguments.get("sub_mode", "hashed_user_id"),
            "access_code_validity": arguments.get("access_code_validity", "minutes=1"),
            "access_token_validity": arguments.get("access_token_validity", "minutes=5"),
            "refresh_token_validity": arguments.get("refresh_token_validity", "days=30"),
            "include_claims_in_id_token": arguments.get("include_claims_in_id_token", True),
        }
        data = await client.post("providers/oauth2/", body)
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    if name == "list_flows":
        params = {
            "page": str(arguments.get("page", 1)),
            "page_size": str(arguments.get("page_size", 20)),
        }
        if arguments.get("designation"):
            params["designation"] = arguments["designation"]
        if arguments.get("search"):
            params["search"] = arguments["search"]
        data = await client.get("flows/instances/", **params)
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    if name == "list_sources":
        params = {
            "page": str(arguments.get("page", 1)),
            "page_size": str(arguments.get("page_size", 20)),
        }
        if arguments.get("search"):
            params["search"] = arguments["search"]
        data = await client.get("sources/all/", **params)
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    if name == "create_oauth_source":
        body = {
            "name": arguments["name"],
            "slug": arguments["slug"],
            "provider_type": arguments["provider_type"],
            "consumer_key": arguments["consumer_key"],
            "consumer_secret": arguments["consumer_secret"],
            "enabled": arguments.get("enabled", True),
            "user_matching_mode": arguments.get("user_matching_mode", "identifier"),
        }
        if arguments.get("authentication_flow"):
            body["authentication_flow"] = arguments["authentication_flow"]
        if arguments.get("enrollment_flow"):
            body["enrollment_flow"] = arguments["enrollment_flow"]
        if arguments.get("access_token_url"):
            body["access_token_url"] = arguments["access_token_url"]
        if arguments.get("authorization_url"):
            body["authorization_url"] = arguments["authorization_url"]
        if arguments.get("profile_url"):
            body["profile_url"] = arguments["profile_url"]
        if arguments.get("oidc_jwks_url"):
            body["oidc_jwks_url"] = arguments["oidc_jwks_url"]
        if arguments.get("additional_scopes"):
            body["additional_scopes"] = arguments["additional_scopes"]
        data = await client.post("sources/oauth/", body)
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
