#!/usr/bin/env python3
"""
Dry-run tests for Grafana MCP + Authentik MCP.
Runs 10 use cases directly against both APIs (no MCP stdio overhead).
"""
import asyncio
import json
import sys
import os

# ── path setup ───────────────────────────────────────────────────────────────
BASE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(BASE, "grafanamcp", "src"))
sys.path.insert(0, os.path.join(BASE, "authentikmcp", "src"))

from grafana_mcp.client import GrafanaClient
from authentik_mcp.client import AuthentikClient

PASS = "✅"
FAIL = "❌"
SEP  = "─" * 60


def section(title: str) -> None:
    print(f"\n{SEP}\n  {title}\n{SEP}")


def ok(label: str, data) -> None:
    # Print a concise preview
    preview = json.dumps(data, indent=2) if isinstance(data, (dict, list)) else str(data)
    lines = preview.splitlines()
    snippet = "\n    ".join(lines[:8]) + ("\n    ..." if len(lines) > 8 else "")
    print(f"{PASS}  {label}\n    {snippet}\n")


def fail(label: str, exc: Exception) -> None:
    print(f"{FAIL}  {label}\n    ERROR: {exc}\n")


# ═══════════════════════════════════════════════════════════════════════════════
# GRAFANA TESTS (5)
# ═══════════════════════════════════════════════════════════════════════════════

async def grafana_tests() -> None:
    section("GRAFANA (5 tests)")
    g = GrafanaClient()

    # 1 — Health check
    try:
        data = await g.get("health")
        ok("1 · health_check — Grafana is alive", data)
    except Exception as e:
        fail("1 · health_check", e)

    # 2 — List all dashboards
    try:
        data = await g.get("search", type="dash-db", limit="50")
        count = len(data) if isinstance(data, list) else "?"
        ok(f"2 · list_dashboards — found {count} dashboards", data[:3] if isinstance(data, list) else data)
    except Exception as e:
        fail("2 · list_dashboards", e)

    # 3 — List data sources
    try:
        data = await g.get("datasources")
        count = len(data) if isinstance(data, list) else "?"
        ok(f"3 · list_datasources — found {count} data sources", data)
    except Exception as e:
        fail("3 · list_datasources", e)

    # 4 — List folders
    try:
        data = await g.get("folders", limit="50")
        count = len(data) if isinstance(data, list) else "?"
        ok(f"4 · list_folders — found {count} folders", data)
    except Exception as e:
        fail("4 · list_folders", e)

    # 5 — Create a demo dashboard (Synology / Portainer theme)
    try:
        dashboard = {
            "title": "MCP Dry-Run — Synology & Portainer Overview",
            "tags": ["mcp", "synology", "portainer", "dry-run"],
            "timezone": "browser",
            "schemaVersion": 38,
            "version": 0,
            "refresh": "30s",
            "panels": [
                {
                    "id": 1,
                    "title": "Portainer — Running Containers",
                    "type": "stat",
                    "gridPos": {"h": 4, "w": 6, "x": 0, "y": 0},
                    "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "orientation": "auto", "textMode": "auto", "colorMode": "background"},
                    "targets": [],
                    "description": "Total running Docker containers on bab1docker (Synology NAS)",
                },
                {
                    "id": 2,
                    "title": "Synology — Docker Host",
                    "type": "text",
                    "gridPos": {"h": 4, "w": 18, "x": 6, "y": 0},
                    "options": {
                        "mode": "markdown",
                        "content": "## Synology NAS — bab1docker\n**Host:** `192.168.110.194:9001`\n\n| Container | Image | Status |\n|---|---|---|\n| gitea | gitea/gitea:1.25.4 | ✅ Up 3 weeks |\n| aria2 | p3terx/aria2-pro | ✅ Up 3 weeks |\n| ariang | p3terx/ariang | ✅ Up 40h |\n| WATCHTOWER | containrrr/watchtower | ✅ Up 3 weeks (healthy) |\n| portainer_agent | portainer/agent:2.27.6 | ✅ Up 3 weeks |",
                    },
                },
                {
                    "id": 3,
                    "title": "Gitea — Memory Limit",
                    "type": "gauge",
                    "gridPos": {"h": 4, "w": 8, "x": 0, "y": 4},
                    "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "minVizHeight": 75, "minVizWidth": 75},
                    "fieldConfig": {
                        "defaults": {
                            "min": 0, "max": 512,
                            "unit": "decmbytes",
                            "thresholds": {
                                "mode": "absolute",
                                "steps": [
                                    {"color": "green", "value": None},
                                    {"color": "yellow", "value": 192},
                                    {"color": "red", "value": 256},
                                ],
                            },
                        }
                    },
                    "targets": [],
                    "description": "Gitea is configured with 256 MB memory limit (swap: 512 MB)",
                },
            ],
        }
        body = {"dashboard": dashboard, "message": "Created by Grafana MCP dry-run test", "overwrite": True}
        data = await g.post("dashboards/db", body)
        ok("5 · create_dashboard — Synology & Portainer overview dashboard", data)
    except Exception as e:
        fail("5 · create_dashboard", e)


# ═══════════════════════════════════════════════════════════════════════════════
# AUTHENTIK TESTS (5)
# ═══════════════════════════════════════════════════════════════════════════════

async def authentik_tests() -> None:
    section("AUTHENTIK (5 tests)")
    a = AuthentikClient()

    # 6 — Health check
    try:
        data = await a.get("root/config/")
        ok("6 · health_check — Authentik is alive", data)
    except Exception as e:
        fail("6 · health_check", e)

    # 7 — List users
    try:
        data = await a.get("core/users/", page="1", page_size="10")
        count = data.get("count", "?") if isinstance(data, dict) else "?"
        results = data.get("results", data)[:3] if isinstance(data, dict) else data
        ok(f"7 · list_users — {count} total users (showing first 3)", results)
    except Exception as e:
        fail("7 · list_users", e)

    # 8 — List applications
    try:
        data = await a.get("core/applications/", page="1", page_size="20")
        count = data.get("count", "?") if isinstance(data, dict) else "?"
        results = data.get("results", [])
        names = [r.get("name") for r in results] if isinstance(results, list) else results
        ok(f"8 · list_applications — {count} apps: {names}", {"count": count, "apps": names})
    except Exception as e:
        fail("8 · list_applications", e)

    # 9 — List flows (find authorization flows)
    try:
        data = await a.get("flows/instances/", designation="authorization", page="1", page_size="10")
        results = data.get("results", []) if isinstance(data, dict) else []
        flows = [{"slug": r.get("slug"), "name": r.get("name")} for r in results]
        ok(f"9 · list_flows (authorization) — found {len(flows)} flow(s)", flows)
    except Exception as e:
        fail("9 · list_flows", e)

    # 10 — Create a test user
    try:
        body = {
            "username": "mcp-dry-run-user",
            "name": "MCP Dry Run User",
            "email": "mcp-dry-run@local.test",
            "is_active": True,
            "type": "internal",
        }
        data = await a.post("core/users/", body)
        ok("10 · create_user — created 'mcp-dry-run-user'", {"pk": data.get("pk"), "username": data.get("username"), "email": data.get("email")})
    except Exception as e:
        # 400 with "username already exists" is still a success (was created before)
        if "already exists" in str(e).lower() or "unique" in str(e).lower():
            ok("10 · create_user — user 'mcp-dry-run-user' already exists (created on prior run)", {"note": str(e)})
        else:
            fail("10 · create_user", e)


# ═══════════════════════════════════════════════════════════════════════════════

async def main() -> None:
    print("\n" + "═" * 60)
    print("  MCP DRY-RUN TEST SUITE — Grafana + Authentik")
    print("═" * 60)
    await grafana_tests()
    await authentik_tests()
    print(f"\n{SEP}\n  All tests complete.\n{SEP}\n")


if __name__ == "__main__":
    asyncio.run(main())
