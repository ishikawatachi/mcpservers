"""
Grafana MCP Server — enhanced edition.

Tools (37):
  Health
    1.  health_check             — verify connectivity and token validity

  Dashboards
    2.  list_dashboards          — search dashboards by query / folder
    3.  get_dashboard            — fetch full dashboard JSON by UID
    4.  get_dashboard_summary    — compact dashboard overview (no full JSON)
    5.  get_dashboard_panel_queries — panel queries and datasource info
    6.  create_dashboard         — create / update a dashboard from JSON
    7.  delete_dashboard         — delete a dashboard by UID

  Datasources
    8.  list_datasources         — list all configured data sources
    9.  get_datasource           — fetch one datasource by UID or name

  Folders
    10. list_folders             — list all dashboard folders
    11. get_folder               — fetch one folder by UID
    12. create_folder            — create a new folder
    13. delete_folder            — delete a folder by UID

  Prometheus
    14. query_prometheus         — execute instant or range PromQL query
    15. list_prometheus_metric_names — list available metric names
    16. list_prometheus_label_names  — list label names (optionally filtered)
    17. list_prometheus_label_values — list values for a label

  Loki
    18. query_loki_logs          — run a LogQL query
    19. list_loki_label_names    — list all label names in Loki
    20. list_loki_label_values   — list values for a Loki label
    21. query_loki_stats         — stream series statistics

  Alerting
    22. list_alerts              — list provisioning alert rules
    23. get_alert_rule           — fetch one alert rule by UID
    24. create_alert_rule        — create a new provisioning alert rule
    25. update_alert_rule        — replace an existing alert rule
    26. delete_alert_rule        — delete an alert rule by UID
    27. list_contact_points      — list notification contact points
    28. list_notification_policies — get the notification routing tree

  Annotations
    29. list_annotations         — query annotations with filters
    30. create_annotation        — create a new annotation
    31. update_annotation        — patch an existing annotation
    32. delete_annotation        — delete an annotation by ID
    33. get_annotation_tags      — list annotation tags

  Admin
    34. list_users               — list Grafana users (admin token required)
    35. list_teams               — list all teams
    36. get_org                  — get current organisation info

  Navigation
    37. generate_deeplink        — build an accurate Grafana deep-link URL

Run:
    grafana-mcp
    # or
    python -m grafana_mcp.server
"""
from __future__ import annotations

import asyncio
import json
import mcp.server.stdio
from mcp.server import Server
from mcp.types import Tool, TextContent

import httpx
import structlog

from grafana_mcp.config import get_settings
from grafana_mcp.client import GrafanaClient

log = structlog.get_logger(__name__)

app = Server("grafana-mcp")

# ---------------------------------------------------------------------------
# Tool registry — maps tool name → async handler(client, args) → list[TextContent]
# ---------------------------------------------------------------------------
_HANDLERS: dict[str, object] = {}


def _handler(name: str):
    def decorator(fn):
        _HANDLERS[name] = fn
        return fn
    return decorator


# ---------------------------------------------------------------------------
# ── Health ──────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@_handler("health_check")
async def _health_check(client: GrafanaClient, args: dict) -> list[TextContent]:
    data = await client.get("health")
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


# ---------------------------------------------------------------------------
# ── Dashboards ───────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@_handler("list_dashboards")
async def _list_dashboards(client: GrafanaClient, args: dict) -> list[TextContent]:
    params: dict[str, str] = {"type": "dash-db"}
    if args.get("query"):
        params["query"] = args["query"]
    if args.get("folder_uid"):
        params["folderUIDs"] = args["folder_uid"]
    params["limit"] = str(args.get("limit", 100))
    data = await client.get("search", **params)
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("get_dashboard")
async def _get_dashboard(client: GrafanaClient, args: dict) -> list[TextContent]:
    data = await client.get(f"dashboards/uid/{args['uid']}")
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("get_dashboard_summary")
async def _get_dashboard_summary(client: GrafanaClient, args: dict) -> list[TextContent]:
    raw = await client.get(f"dashboards/uid/{args['uid']}")
    db = raw.get("dashboard", {})
    meta = raw.get("meta", {})
    panels = db.get("panels", [])
    panel_types = sorted({p.get("type", "unknown") for p in panels})
    variables = db.get("templating", {}).get("list", [])
    summary = {
        "uid": db.get("uid"),
        "title": db.get("title"),
        "tags": db.get("tags", []),
        "folder_uid": meta.get("folderUid"),
        "folder_title": meta.get("folderTitle"),
        "panel_count": len(panels),
        "panel_types": panel_types,
        "variable_count": len(variables),
        "time_from": db.get("time", {}).get("from"),
        "time_to": db.get("time", {}).get("to"),
        "schemaVersion": db.get("schemaVersion"),
        "version": db.get("version"),
    }
    return [TextContent(type="text", text=json.dumps(summary, indent=2))]


@_handler("get_dashboard_panel_queries")
async def _get_dashboard_panel_queries(client: GrafanaClient, args: dict) -> list[TextContent]:
    raw = await client.get(f"dashboards/uid/{args['uid']}")
    panels = raw.get("dashboard", {}).get("panels", [])
    result = []
    for panel in panels:
        ds = panel.get("datasource") or {}
        result.append({
            "panel_id": panel.get("id"),
            "panel_title": panel.get("title"),
            "panel_type": panel.get("type"),
            "datasource_uid": ds.get("uid") if isinstance(ds, dict) else None,
            "datasource_type": ds.get("type") if isinstance(ds, dict) else None,
            "targets": panel.get("targets", []),
        })
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


@_handler("create_dashboard")
async def _create_dashboard(client: GrafanaClient, args: dict) -> list[TextContent]:
    dashboard = json.loads(args["dashboard_json"])
    dashboard.setdefault("schemaVersion", 38)
    dashboard.setdefault("version", 0)
    dashboard.setdefault("timezone", "browser")
    dashboard.setdefault("panels", [])
    body: dict = {
        "dashboard": dashboard,
        "message": args.get("message", "Created via Grafana MCP"),
        "overwrite": args.get("overwrite", False),
    }
    if args.get("folder_uid"):
        body["folderUid"] = args["folder_uid"]
    data = await client.post("dashboards/db", body)
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("delete_dashboard")
async def _delete_dashboard(client: GrafanaClient, args: dict) -> list[TextContent]:
    data = await client.delete(f"dashboards/uid/{args['uid']}")
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


# ---------------------------------------------------------------------------
# ── Datasources ──────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@_handler("list_datasources")
async def _list_datasources(client: GrafanaClient, args: dict) -> list[TextContent]:
    data = await client.get("datasources")
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("get_datasource")
async def _get_datasource(client: GrafanaClient, args: dict) -> list[TextContent]:
    if args.get("uid"):
        data = await client.get(f"datasources/uid/{args['uid']}")
    elif args.get("name"):
        data = await client.get(f"datasources/name/{args['name']}")
    else:
        raise ValueError("Provide either 'uid' or 'name'")
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


# ---------------------------------------------------------------------------
# ── Folders ──────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@_handler("list_folders")
async def _list_folders(client: GrafanaClient, args: dict) -> list[TextContent]:
    data = await client.get("folders", limit=str(args.get("limit", 100)))
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("get_folder")
async def _get_folder(client: GrafanaClient, args: dict) -> list[TextContent]:
    data = await client.get(f"folders/{args['uid']}")
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("create_folder")
async def _create_folder(client: GrafanaClient, args: dict) -> list[TextContent]:
    body: dict = {"title": args["title"]}
    if args.get("uid"):
        body["uid"] = args["uid"]
    data = await client.post("folders", body)
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("delete_folder")
async def _delete_folder(client: GrafanaClient, args: dict) -> list[TextContent]:
    data = await client.delete(f"folders/{args['uid']}")
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


# ---------------------------------------------------------------------------
# ── Prometheus ───────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@_handler("query_prometheus")
async def _query_prometheus(client: GrafanaClient, args: dict) -> list[TextContent]:
    ds_uid = args["datasource_uid"]
    expr = args["expr"]
    query_type = args.get("query_type", "instant")
    if query_type == "range":
        params: dict[str, str] = {
            "query": expr,
            "start": str(args.get("start", "")),
            "end": str(args.get("end", "")),
            "step": str(args.get("step", "60")),
        }
        data = await client.get(f"datasources/proxy/uid/{ds_uid}/api/v1/query_range", **params)
    else:
        params = {"query": expr}
        if args.get("time"):
            params["time"] = str(args["time"])
        data = await client.get(f"datasources/proxy/uid/{ds_uid}/api/v1/query", **params)
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("list_prometheus_metric_names")
async def _list_prometheus_metric_names(client: GrafanaClient, args: dict) -> list[TextContent]:
    ds_uid = args["datasource_uid"]
    params: dict[str, str] = {}
    if args.get("start"):
        params["start"] = str(args["start"])
    if args.get("end"):
        params["end"] = str(args["end"])
    data = await client.get(f"datasources/proxy/uid/{ds_uid}/api/v1/label/__name__/values", **params)
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("list_prometheus_label_names")
async def _list_prometheus_label_names(client: GrafanaClient, args: dict) -> list[TextContent]:
    ds_uid = args["datasource_uid"]
    params: dict[str, str] = {}
    if args.get("start"):
        params["start"] = str(args["start"])
    if args.get("end"):
        params["end"] = str(args["end"])
    data = await client.get(f"datasources/proxy/uid/{ds_uid}/api/v1/labels", **params)
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("list_prometheus_label_values")
async def _list_prometheus_label_values(client: GrafanaClient, args: dict) -> list[TextContent]:
    ds_uid = args["datasource_uid"]
    label = args["label_name"]
    params: dict[str, str] = {}
    if args.get("start"):
        params["start"] = str(args["start"])
    if args.get("end"):
        params["end"] = str(args["end"])
    data = await client.get(f"datasources/proxy/uid/{ds_uid}/api/v1/label/{label}/values", **params)
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


# ---------------------------------------------------------------------------
# ── Loki ─────────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@_handler("query_loki_logs")
async def _query_loki_logs(client: GrafanaClient, args: dict) -> list[TextContent]:
    ds_uid = args["datasource_uid"]
    params: dict[str, str] = {"query": args["query"]}
    if args.get("start"):
        params["start"] = str(args["start"])
    if args.get("end"):
        params["end"] = str(args["end"])
    params["limit"] = str(args.get("limit", 100))
    params["direction"] = args.get("direction", "backward")
    data = await client.get(
        f"datasources/proxy/uid/{ds_uid}/loki/api/v1/query_range", **params
    )
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("list_loki_label_names")
async def _list_loki_label_names(client: GrafanaClient, args: dict) -> list[TextContent]:
    ds_uid = args["datasource_uid"]
    params: dict[str, str] = {}
    if args.get("start"):
        params["start"] = str(args["start"])
    if args.get("end"):
        params["end"] = str(args["end"])
    data = await client.get(f"datasources/proxy/uid/{ds_uid}/loki/api/v1/labels", **params)
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("list_loki_label_values")
async def _list_loki_label_values(client: GrafanaClient, args: dict) -> list[TextContent]:
    ds_uid = args["datasource_uid"]
    label = args["label_name"]
    params: dict[str, str] = {}
    if args.get("start"):
        params["start"] = str(args["start"])
    if args.get("end"):
        params["end"] = str(args["end"])
    data = await client.get(
        f"datasources/proxy/uid/{ds_uid}/loki/api/v1/label/{label}/values", **params
    )
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("query_loki_stats")
async def _query_loki_stats(client: GrafanaClient, args: dict) -> list[TextContent]:
    ds_uid = args["datasource_uid"]
    params: dict[str, str] = {}
    if args.get("query"):
        params["match[]"] = args["query"]
    if args.get("start"):
        params["start"] = str(args["start"])
    if args.get("end"):
        params["end"] = str(args["end"])
    data = await client.get(f"datasources/proxy/uid/{ds_uid}/loki/api/v1/series", **params)
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


# ---------------------------------------------------------------------------
# ── Alerting ─────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@_handler("list_alerts")
async def _list_alerts(client: GrafanaClient, args: dict) -> list[TextContent]:
    data = await client.get("v1/provisioning/alert-rules")
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("get_alert_rule")
async def _get_alert_rule(client: GrafanaClient, args: dict) -> list[TextContent]:
    data = await client.get(f"v1/provisioning/alert-rules/{args['uid']}")
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("create_alert_rule")
async def _create_alert_rule(client: GrafanaClient, args: dict) -> list[TextContent]:
    rule = json.loads(args["rule_json"])
    data = await client.post("v1/provisioning/alert-rules", rule)
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("update_alert_rule")
async def _update_alert_rule(client: GrafanaClient, args: dict) -> list[TextContent]:
    rule = json.loads(args["rule_json"])
    data = await client.put(f"v1/provisioning/alert-rules/{args['uid']}", rule)
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("delete_alert_rule")
async def _delete_alert_rule(client: GrafanaClient, args: dict) -> list[TextContent]:
    data = await client.delete(f"v1/provisioning/alert-rules/{args['uid']}")
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("list_contact_points")
async def _list_contact_points(client: GrafanaClient, args: dict) -> list[TextContent]:
    data = await client.get("v1/provisioning/contact-points")
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("list_notification_policies")
async def _list_notification_policies(client: GrafanaClient, args: dict) -> list[TextContent]:
    data = await client.get("v1/provisioning/policies")
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


# ---------------------------------------------------------------------------
# ── Annotations ───────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@_handler("list_annotations")
async def _list_annotations(client: GrafanaClient, args: dict) -> list[TextContent]:
    params: dict[str, str] = {}
    if args.get("from_ms"):
        params["from"] = str(args["from_ms"])
    if args.get("to_ms"):
        params["to"] = str(args["to_ms"])
    if args.get("dashboard_uid"):
        params["dashboardUID"] = args["dashboard_uid"]
    if args.get("dashboard_id"):
        params["dashboardId"] = str(args["dashboard_id"])
    if args.get("tags"):
        params["tags"] = args["tags"]
    params["limit"] = str(args.get("limit", 100))
    data = await client.get("annotations", **params)
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("create_annotation")
async def _create_annotation(client: GrafanaClient, args: dict) -> list[TextContent]:
    body: dict = {"text": args["text"]}
    if args.get("dashboard_uid"):
        body["dashboardUID"] = args["dashboard_uid"]
    if args.get("panel_id"):
        body["panelId"] = args["panel_id"]
    if args.get("time_ms"):
        body["time"] = args["time_ms"]
    if args.get("time_end_ms"):
        body["timeEnd"] = args["time_end_ms"]
    if args.get("tags"):
        body["tags"] = args["tags"]
    data = await client.post("annotations", body)
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("update_annotation")
async def _update_annotation(client: GrafanaClient, args: dict) -> list[TextContent]:
    body: dict = {}
    if args.get("text"):
        body["text"] = args["text"]
    if args.get("tags"):
        body["tags"] = args["tags"]
    if args.get("time_ms"):
        body["time"] = args["time_ms"]
    if args.get("time_end_ms"):
        body["timeEnd"] = args["time_end_ms"]
    data = await client.patch(f"annotations/{args['annotation_id']}", body)
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("delete_annotation")
async def _delete_annotation(client: GrafanaClient, args: dict) -> list[TextContent]:
    data = await client.delete(f"annotations/{args['annotation_id']}")
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("get_annotation_tags")
async def _get_annotation_tags(client: GrafanaClient, args: dict) -> list[TextContent]:
    params: dict[str, str] = {}
    if args.get("tag"):
        params["tag"] = args["tag"]
    params["limit"] = str(args.get("limit", 100))
    data = await client.get("annotations/tags", **params)
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


# ---------------------------------------------------------------------------
# ── Admin ─────────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@_handler("list_users")
async def _list_users(client: GrafanaClient, args: dict) -> list[TextContent]:
    params: dict[str, str] = {
        "page": str(args.get("page", 1)),
        "perpage": str(args.get("perpage", 50)),
    }
    if args.get("query"):
        params["query"] = args["query"]
    data = await client.get("users", **params)
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("list_teams")
async def _list_teams(client: GrafanaClient, args: dict) -> list[TextContent]:
    params: dict[str, str] = {"perpage": str(args.get("perpage", 50))}
    if args.get("query"):
        params["query"] = args["query"]
    data = await client.get("teams/search", **params)
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


@_handler("get_org")
async def _get_org(client: GrafanaClient, args: dict) -> list[TextContent]:
    data = await client.get("org")
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


# ---------------------------------------------------------------------------
# ── Navigation ────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@_handler("generate_deeplink")
async def _generate_deeplink(client: GrafanaClient, args: dict) -> list[TextContent]:
    from urllib.parse import urlencode
    cfg = get_settings()
    base = cfg.grafana_url
    resource_type = args["resource_type"]
    uid = args.get("uid", "")

    extra: dict[str, str] = {}
    if args.get("from_time"):
        extra["from"] = args["from_time"]
    if args.get("to_time"):
        extra["to"] = args["to_time"]
    if args.get("extra_params") and isinstance(args["extra_params"], dict):
        extra.update({str(k): str(v) for k, v in args["extra_params"].items()})

    if resource_type == "dashboard":
        url = f"{base}/d/{uid}"
    elif resource_type == "panel":
        panel_id = args.get("panel_id", 1)
        extra["viewPanel"] = str(panel_id)
        url = f"{base}/d/{uid}"
    elif resource_type == "explore":
        ds_uid = args.get("datasource_uid", "")
        left_obj = {"datasource": ds_uid, "queries": [{"datasource": {"uid": ds_uid}}]}
        if args.get("query"):
            left_obj["queries"][0]["expr"] = args["query"]
        extra["left"] = json.dumps(left_obj)
        url = f"{base}/explore"
    elif resource_type == "folder":
        url = f"{base}/dashboards/f/{uid}"
    elif resource_type == "alerting":
        url = f"{base}/alerting"
    else:
        raise ValueError(f"Unknown resource_type: {resource_type!r}. Use: dashboard, panel, explore, folder, alerting")

    if extra:
        url = f"{url}?{urlencode(extra)}"

    return [TextContent(type="text", text=url)]


# ---------------------------------------------------------------------------
# ── Tool schema registry ────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@app.list_tools()
async def list_tools() -> list[Tool]:  # noqa: F811 (overrides test stub if any)
    return [
        # ── Health ──────────────────────────────────────────────────────────
        Tool(
            name="health_check",
            description="Validate Grafana connectivity and API token. Returns version and database status.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        # ── Dashboards ───────────────────────────────────────────────────────
        Tool(
            name="list_dashboards",
            description="Search and list dashboards. Optionally filter by search query string or folder UID.",
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
            description=(
                "Fetch the full JSON model of a dashboard by its UID. "
                "WARNING: large dashboards can consume significant context. "
                "Prefer get_dashboard_summary for overviews."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "uid": {"type": "string", "description": "Dashboard UID (visible in the dashboard URL)."},
                },
                "required": ["uid"],
            },
        ),
        Tool(
            name="get_dashboard_summary",
            description=(
                "Get a compact overview of a dashboard: title, tags, folder, panel count, panel types, "
                "variables, and time range — without the full JSON payload."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "uid": {"type": "string", "description": "Dashboard UID."},
                },
                "required": ["uid"],
            },
        ),
        Tool(
            name="get_dashboard_panel_queries",
            description=(
                "Extract panel IDs, titles, types, datasource info, and query targets from a dashboard. "
                "Use this to find which PromQL / LogQL queries power each panel."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "uid": {"type": "string", "description": "Dashboard UID."},
                },
                "required": ["uid"],
            },
        ),
        Tool(
            name="create_dashboard",
            description=(
                "Create a new dashboard or update an existing one. "
                "Provide a complete Grafana dashboard JSON object as dashboard_json. "
                "Set overwrite=true to update an existing dashboard by UID."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "dashboard_json": {
                        "type": "string",
                        "description": "JSON string of the Grafana dashboard model (must include title).",
                    },
                    "folder_uid": {"type": "string", "description": "Folder UID (defaults to General/root)."},
                    "message": {"type": "string", "description": "Commit message.", "default": "Created via Grafana MCP"},
                    "overwrite": {"type": "boolean", "description": "Overwrite dashboard with same UID.", "default": False},
                },
                "required": ["dashboard_json"],
            },
        ),
        Tool(
            name="delete_dashboard",
            description="Delete a dashboard by its UID. This action is irreversible.",
            inputSchema={
                "type": "object",
                "properties": {
                    "uid": {"type": "string", "description": "Dashboard UID to delete."},
                },
                "required": ["uid"],
            },
        ),
        # ── Datasources ──────────────────────────────────────────────────────
        Tool(
            name="list_datasources",
            description="List all data sources configured in Grafana.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_datasource",
            description="Fetch a single data source by UID or name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "uid": {"type": "string", "description": "Datasource UID."},
                    "name": {"type": "string", "description": "Datasource name (used if uid not provided)."},
                },
                "required": [],
            },
        ),
        # ── Folders ──────────────────────────────────────────────────────────
        Tool(
            name="list_folders",
            description="List all dashboard folders.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max folders to return (default 100).", "default": 100},
                },
                "required": [],
            },
        ),
        Tool(
            name="get_folder",
            description="Fetch a single folder by its UID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "uid": {"type": "string", "description": "Folder UID."},
                },
                "required": ["uid"],
            },
        ),
        Tool(
            name="create_folder",
            description="Create a new Grafana dashboard folder.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Display name for the folder."},
                    "uid": {"type": "string", "description": "Optional UID for the folder (auto-generated if omitted)."},
                },
                "required": ["title"],
            },
        ),
        Tool(
            name="delete_folder",
            description="Delete a folder (and optionally its dashboards) by UID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "uid": {"type": "string", "description": "Folder UID to delete."},
                },
                "required": ["uid"],
            },
        ),
        # ── Prometheus ───────────────────────────────────────────────────────
        Tool(
            name="query_prometheus",
            description=(
                "Execute a PromQL query against a Prometheus datasource. "
                "Use query_type='instant' for a single point in time or 'range' for a time series. "
                "Requires the datasource UID (get it from list_datasources)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "datasource_uid": {"type": "string", "description": "Prometheus datasource UID."},
                    "expr": {"type": "string", "description": "PromQL expression to evaluate."},
                    "query_type": {
                        "type": "string",
                        "enum": ["instant", "range"],
                        "description": "instant (default) or range query.",
                        "default": "instant",
                    },
                    "time": {"type": "number", "description": "Evaluation timestamp (Unix seconds) for instant queries."},
                    "start": {"type": "number", "description": "Range start (Unix seconds) for range queries."},
                    "end": {"type": "number", "description": "Range end (Unix seconds) for range queries."},
                    "step": {"type": "string", "description": "Step interval for range queries (e.g. '60' or '5m').", "default": "60"},
                },
                "required": ["datasource_uid", "expr"],
            },
        ),
        Tool(
            name="list_prometheus_metric_names",
            description="List all available metric names in a Prometheus datasource.",
            inputSchema={
                "type": "object",
                "properties": {
                    "datasource_uid": {"type": "string", "description": "Prometheus datasource UID."},
                    "start": {"type": "number", "description": "Start of time range (Unix seconds)."},
                    "end": {"type": "number", "description": "End of time range (Unix seconds)."},
                },
                "required": ["datasource_uid"],
            },
        ),
        Tool(
            name="list_prometheus_label_names",
            description="List all label names available in a Prometheus datasource.",
            inputSchema={
                "type": "object",
                "properties": {
                    "datasource_uid": {"type": "string", "description": "Prometheus datasource UID."},
                    "start": {"type": "number", "description": "Start of time range (Unix seconds)."},
                    "end": {"type": "number", "description": "End of time range (Unix seconds)."},
                },
                "required": ["datasource_uid"],
            },
        ),
        Tool(
            name="list_prometheus_label_values",
            description="List all values for a given label name in a Prometheus datasource.",
            inputSchema={
                "type": "object",
                "properties": {
                    "datasource_uid": {"type": "string", "description": "Prometheus datasource UID."},
                    "label_name": {"type": "string", "description": "Label name to retrieve values for."},
                    "start": {"type": "number", "description": "Start of time range (Unix seconds)."},
                    "end": {"type": "number", "description": "End of time range (Unix seconds)."},
                },
                "required": ["datasource_uid", "label_name"],
            },
        ),
        # ── Loki ─────────────────────────────────────────────────────────────
        Tool(
            name="query_loki_logs",
            description=(
                "Run a LogQL query against a Loki datasource and return matching log lines. "
                "Use {label='value'} selectors and optional filter expressions. "
                "Requires the Loki datasource UID (get it from list_datasources)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "datasource_uid": {"type": "string", "description": "Loki datasource UID."},
                    "query": {"type": "string", "description": "LogQL query string (e.g. '{job=\"app\"} |= \"error\"')."},
                    "start": {"type": "string", "description": "Start time as Unix nanoseconds or ISO 8601 string."},
                    "end": {"type": "string", "description": "End time as Unix nanoseconds or ISO 8601 string."},
                    "limit": {"type": "integer", "description": "Maximum log lines to return (default 100).", "default": 100},
                    "direction": {
                        "type": "string",
                        "enum": ["backward", "forward"],
                        "description": "Log order: backward (newest first, default) or forward.",
                        "default": "backward",
                    },
                },
                "required": ["datasource_uid", "query"],
            },
        ),
        Tool(
            name="list_loki_label_names",
            description="List all label names stored in a Loki datasource.",
            inputSchema={
                "type": "object",
                "properties": {
                    "datasource_uid": {"type": "string", "description": "Loki datasource UID."},
                    "start": {"type": "string", "description": "Start time (Unix nanoseconds or ISO 8601)."},
                    "end": {"type": "string", "description": "End time (Unix nanoseconds or ISO 8601)."},
                },
                "required": ["datasource_uid"],
            },
        ),
        Tool(
            name="list_loki_label_values",
            description="List all values for a specific label in a Loki datasource.",
            inputSchema={
                "type": "object",
                "properties": {
                    "datasource_uid": {"type": "string", "description": "Loki datasource UID."},
                    "label_name": {"type": "string", "description": "Label name to retrieve values for."},
                    "start": {"type": "string", "description": "Start time (Unix nanoseconds or ISO 8601)."},
                    "end": {"type": "string", "description": "End time (Unix nanoseconds or ISO 8601)."},
                },
                "required": ["datasource_uid", "label_name"],
            },
        ),
        Tool(
            name="query_loki_stats",
            description="Return stream series matching a Loki selector. Useful for exploring what streams exist.",
            inputSchema={
                "type": "object",
                "properties": {
                    "datasource_uid": {"type": "string", "description": "Loki datasource UID."},
                    "query": {"type": "string", "description": "Stream selector (e.g. '{job=\"app\"}')."},
                    "start": {"type": "string", "description": "Start time (Unix nanoseconds or ISO 8601)."},
                    "end": {"type": "string", "description": "End time (Unix nanoseconds or ISO 8601)."},
                },
                "required": ["datasource_uid"],
            },
        ),
        # ── Alerting ─────────────────────────────────────────────────────────
        Tool(
            name="list_alerts",
            description="List all provisioning alert rules.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_alert_rule",
            description="Fetch a single provisioning alert rule by its UID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "uid": {"type": "string", "description": "Alert rule UID."},
                },
                "required": ["uid"],
            },
        ),
        Tool(
            name="create_alert_rule",
            description=(
                "Create a new Grafana provisioning alert rule. "
                "Provide the full alert rule JSON as rule_json. "
                "Must include title, condition, data, folderUID, and ruleGroup."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "rule_json": {"type": "string", "description": "JSON string of the alert rule."},
                },
                "required": ["rule_json"],
            },
        ),
        Tool(
            name="update_alert_rule",
            description="Replace an existing provisioning alert rule (full update by UID).",
            inputSchema={
                "type": "object",
                "properties": {
                    "uid": {"type": "string", "description": "Alert rule UID to update."},
                    "rule_json": {"type": "string", "description": "New alert rule JSON."},
                },
                "required": ["uid", "rule_json"],
            },
        ),
        Tool(
            name="delete_alert_rule",
            description="Delete a provisioning alert rule by UID. This action is irreversible.",
            inputSchema={
                "type": "object",
                "properties": {
                    "uid": {"type": "string", "description": "Alert rule UID to delete."},
                },
                "required": ["uid"],
            },
        ),
        Tool(
            name="list_contact_points",
            description="List all notification contact points (email, Slack, PagerDuty, etc.) configured in Grafana.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="list_notification_policies",
            description="Get the full notification routing policy tree.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        # ── Annotations ───────────────────────────────────────────────────────
        Tool(
            name="list_annotations",
            description="Query Grafana annotations. Filter by time range, dashboard UID / ID, tags, or limit.",
            inputSchema={
                "type": "object",
                "properties": {
                    "from_ms": {"type": "integer", "description": "Start of time range in milliseconds epoch."},
                    "to_ms": {"type": "integer", "description": "End of time range in milliseconds epoch."},
                    "dashboard_uid": {"type": "string", "description": "Filter by dashboard UID."},
                    "dashboard_id": {"type": "integer", "description": "Filter by dashboard numeric ID (legacy)."},
                    "tags": {"type": "string", "description": "Filter by tag (repeatable for multiple tags)."},
                    "limit": {"type": "integer", "description": "Max annotations to return (default 100).", "default": 100},
                },
                "required": [],
            },
        ),
        Tool(
            name="create_annotation",
            description="Create a new annotation on a dashboard or panel.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Annotation text / description."},
                    "dashboard_uid": {"type": "string", "description": "Dashboard UID to annotate."},
                    "panel_id": {"type": "integer", "description": "Panel ID within the dashboard."},
                    "time_ms": {"type": "integer", "description": "Annotation time in milliseconds epoch."},
                    "time_end_ms": {"type": "integer", "description": "End time for region annotations (ms epoch)."},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags to attach."},
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="update_annotation",
            description="Partially update an existing annotation's text, tags, or time.",
            inputSchema={
                "type": "object",
                "properties": {
                    "annotation_id": {"type": "integer", "description": "Annotation ID to update."},
                    "text": {"type": "string", "description": "New annotation text."},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "New tag list."},
                    "time_ms": {"type": "integer", "description": "New annotation time (ms epoch)."},
                    "time_end_ms": {"type": "integer", "description": "New end time (ms epoch)."},
                },
                "required": ["annotation_id"],
            },
        ),
        Tool(
            name="delete_annotation",
            description="Delete an annotation by its numeric ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "annotation_id": {"type": "integer", "description": "Annotation ID to delete."},
                },
                "required": ["annotation_id"],
            },
        ),
        Tool(
            name="get_annotation_tags",
            description="List all annotation tags, optionally filtered by a prefix.",
            inputSchema={
                "type": "object",
                "properties": {
                    "tag": {"type": "string", "description": "Optional prefix to filter tags."},
                    "limit": {"type": "integer", "description": "Max tags to return (default 100).", "default": 100},
                },
                "required": [],
            },
        ),
        # ── Admin ─────────────────────────────────────────────────────────────
        Tool(
            name="list_users",
            description="List Grafana users (admin API token required).",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Filter users by login, email, or name."},
                    "page": {"type": "integer", "description": "Page number (default 1).", "default": 1},
                    "perpage": {"type": "integer", "description": "Results per page (default 50).", "default": 50},
                },
                "required": [],
            },
        ),
        Tool(
            name="list_teams",
            description="List all teams in the Grafana organisation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Filter teams by name."},
                    "perpage": {"type": "integer", "description": "Results per page (default 50).", "default": 50},
                },
                "required": [],
            },
        ),
        Tool(
            name="get_org",
            description="Get the current Grafana organisation details.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        # ── Navigation ────────────────────────────────────────────────────────
        Tool(
            name="generate_deeplink",
            description=(
                "Generate an accurate Grafana deep-link URL for a dashboard, panel, Explore view, "
                "folder, or alerting page. Prevents URL guessing errors. "
                "resource_type options: dashboard, panel, explore, folder, alerting."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "resource_type": {
                        "type": "string",
                        "enum": ["dashboard", "panel", "explore", "folder", "alerting"],
                        "description": "Type of Grafana resource to link to.",
                    },
                    "uid": {"type": "string", "description": "UID of the dashboard or folder."},
                    "panel_id": {"type": "integer", "description": "Panel ID (required for resource_type=panel)."},
                    "datasource_uid": {"type": "string", "description": "Datasource UID for resource_type=explore."},
                    "query": {"type": "string", "description": "Pre-filled query string for resource_type=explore."},
                    "from_time": {"type": "string", "description": "Time range start (e.g. 'now-1h')."},
                    "to_time": {"type": "string", "description": "Time range end (e.g. 'now')."},
                    "extra_params": {
                        "type": "object",
                        "description": "Additional URL query parameters as key-value pairs.",
                    },
                },
                "required": ["resource_type"],
            },
        ),
    ]


# ---------------------------------------------------------------------------
# ── Tool dispatcher ──────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name!r}")
    client = GrafanaClient()
    try:
        return await handler(client, arguments or {})
    except httpx.HTTPStatusError as e:
        err = {"error": f"HTTP {e.response.status_code}", "detail": e.response.text[:500]}
        return [TextContent(type="text", text=json.dumps(err, indent=2))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}, indent=2))]


# ---------------------------------------------------------------------------
# ── SSE transport helper ─────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

def _create_sse_app():
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.routing import Mount, Route

    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Request) -> None:
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await app.run(streams[0], streams[1], app.create_initialization_options())

    return Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )


# ---------------------------------------------------------------------------
# ── Entry point ──────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    cfg = get_settings()
    log.info("grafana_mcp.starting", url=cfg.grafana_url)

    parser = argparse.ArgumentParser(description="Grafana MCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio",
                        help="Transport mode (default: stdio)")
    parser.add_argument("--host", default="0.0.0.0", help="SSE host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8003, help="SSE port (default: 8003)")
    args = parser.parse_args()

    if args.transport == "sse":
        import uvicorn
        log.info("grafana_mcp.transport", transport="sse", host=args.host, port=args.port)
        uvicorn.run(_create_sse_app(), host=args.host, port=args.port)
    else:
        asyncio.run(mcp.server.stdio.stdio_server(app))


if __name__ == "__main__":
    main()
