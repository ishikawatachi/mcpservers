"""
Comprehensive test suite for grafanamcp.

Covers:
  - All 37 tools (happy-path responses)
  - HTTP error handling (401, 404, 500)
  - Security properties (token in headers, SSL verify respected, no secrets in output)
  - Config resolution (env vars, keychain fallback)
  - Client patch() and fixed delete() methods

Run:
    cd grafanamcp
    pytest tests/ -v
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from grafana_mcp.client import GrafanaClient
from grafana_mcp.config import Settings

# ---------------------------------------------------------------------------
# Constants and fixtures
# ---------------------------------------------------------------------------

BASE_URL = "http://grafana.test"
TEST_TOKEN = "glsa_test_token_secret_abc123"


def make_settings(**kwargs):
    defaults = dict(grafana_url=BASE_URL, api_token=TEST_TOKEN, ssl_verify=True, timeout=10.0)
    defaults.update(kwargs)
    return Settings(**defaults)


@pytest.fixture(autouse=True)
def mock_settings():
    """Patch get_settings in both client and server modules for every test."""
    s = make_settings()
    with (
        patch("grafana_mcp.client.get_settings", return_value=s),
        patch("grafana_mcp.server.get_settings", return_value=s),
    ):
        yield s


@pytest.fixture
def client():
    return GrafanaClient()


# ---------------------------------------------------------------------------
# Helper: call a tool through the server dispatcher
# ---------------------------------------------------------------------------

async def call_tool(name: str, args: dict = None):
    """Invoke a tool handler with the same error wrapping the real MCP dispatcher applies."""
    from grafana_mcp.server import _HANDLERS
    from grafana_mcp.client import GrafanaClient as _C
    from mcp.types import TextContent

    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name!r}")
    try:
        return await handler(_C(), args or {})
    except httpx.HTTPStatusError as exc:
        return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]
    except Exception as exc:
        return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]


def text_of(result) -> str:
    """Extract the text from a list[TextContent] result."""
    return result[0].text


def json_of(result) -> object:
    return json.loads(text_of(result))


# ---------------------------------------------------------------------------
# ── Client unit tests ────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestGrafanaClient:

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_sends_bearer_token(self, client):
        route = respx.get(f"{BASE_URL}/api/health").mock(
            return_value=httpx.Response(200, json={"database": "ok", "version": "10.0.0"})
        )
        await client.get("health")
        req = route.calls.last.request
        assert req.headers["Authorization"] == f"Bearer {TEST_TOKEN}"

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_returns_json(self, client):
        respx.get(f"{BASE_URL}/api/health").mock(
            return_value=httpx.Response(200, json={"database": "ok"})
        )
        data = await client.get("health")
        assert data == {"database": "ok"}

    @respx.mock
    @pytest.mark.asyncio
    async def test_post_sends_json_content_type(self, client):
        route = respx.post(f"{BASE_URL}/api/dashboards/db").mock(
            return_value=httpx.Response(200, json={"uid": "abc", "status": "success"})
        )
        await client.post("dashboards/db", {"dashboard": {}, "overwrite": False})
        req = route.calls.last.request
        assert req.headers["Content-Type"] == "application/json"

    @respx.mock
    @pytest.mark.asyncio
    async def test_put_sends_json_body(self, client):
        route = respx.put(f"{BASE_URL}/api/v1/provisioning/alert-rules/uid123").mock(
            return_value=httpx.Response(200, json={"uid": "uid123"})
        )
        await client.put("v1/provisioning/alert-rules/uid123", {"title": "new"})
        body = json.loads(route.calls.last.request.content)
        assert body["title"] == "new"

    @respx.mock
    @pytest.mark.asyncio
    async def test_patch_sends_partial_body(self, client):
        route = respx.patch(f"{BASE_URL}/api/annotations/42").mock(
            return_value=httpx.Response(200, json={"message": "Annotation patched"})
        )
        await client.patch("annotations/42", {"text": "updated"})
        body = json.loads(route.calls.last.request.content)
        assert body["text"] == "updated"

    @respx.mock
    @pytest.mark.asyncio
    async def test_delete_204_returns_deleted_status(self, client):
        respx.delete(f"{BASE_URL}/api/v1/provisioning/alert-rules/uid123").mock(
            return_value=httpx.Response(204, content=b"")
        )
        result = await client.delete("v1/provisioning/alert-rules/uid123")
        assert result == {"status": "deleted"}

    @respx.mock
    @pytest.mark.asyncio
    async def test_delete_200_with_json_returns_json(self, client):
        respx.delete(f"{BASE_URL}/api/dashboards/uid/abc").mock(
            return_value=httpx.Response(200, json={"title": "Dash", "message": "Dashboard Dash deleted"})
        )
        result = await client.delete("dashboards/uid/abc")
        assert result["title"] == "Dash"

    @respx.mock
    @pytest.mark.asyncio
    async def test_ssl_verify_false_respected(self):
        s = make_settings(ssl_verify=False)
        with patch("grafana_mcp.client.get_settings", return_value=s):
            c = GrafanaClient()
        assert c._verify is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_on_http_error(self, client):
        respx.get(f"{BASE_URL}/api/health").mock(
            return_value=httpx.Response(401, json={"message": "Unauthorized"})
        )
        with pytest.raises(httpx.HTTPStatusError):
            await client.get("health")


# ---------------------------------------------------------------------------
# ── Health tool ──────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestHealthCheck:

    @respx.mock
    @pytest.mark.asyncio
    async def test_health_check_ok(self):
        respx.get(f"{BASE_URL}/api/health").mock(
            return_value=httpx.Response(200, json={"database": "ok", "version": "10.2.0"})
        )
        result = await call_tool("health_check")
        data = json_of(result)
        assert data["database"] == "ok"

    @respx.mock
    @pytest.mark.asyncio
    async def test_health_check_error_returns_error_json(self):
        respx.get(f"{BASE_URL}/api/health").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        result = await call_tool("health_check")
        data = json_of(result)
        assert "error" in data


# ---------------------------------------------------------------------------
# ── Dashboard tools ───────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestDashboardTools:

    @respx.mock
    @pytest.mark.asyncio
    async def test_list_dashboards_default(self):
        respx.get(f"{BASE_URL}/api/search").mock(
            return_value=httpx.Response(200, json=[{"uid": "d1", "title": "My Dashboard"}])
        )
        result = await call_tool("list_dashboards")
        data = json_of(result)
        assert data[0]["uid"] == "d1"

    @respx.mock
    @pytest.mark.asyncio
    async def test_list_dashboards_with_query(self):
        route = respx.get(f"{BASE_URL}/api/search").mock(
            return_value=httpx.Response(200, json=[])
        )
        await call_tool("list_dashboards", {"query": "prod", "limit": 10})
        params = dict(route.calls.last.request.url.params)
        assert params["query"] == "prod"
        assert params["limit"] == "10"

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_dashboard(self):
        respx.get(f"{BASE_URL}/api/dashboards/uid/abc123").mock(
            return_value=httpx.Response(200, json={
                "dashboard": {"uid": "abc123", "title": "Test", "panels": []},
                "meta": {"folderTitle": "General"}
            })
        )
        result = await call_tool("get_dashboard", {"uid": "abc123"})
        data = json_of(result)
        assert data["dashboard"]["uid"] == "abc123"

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_dashboard_summary(self):
        dashboard_payload = {
            "dashboard": {
                "uid": "abc123", "title": "Node Exporter",
                "tags": ["infra"], "version": 5,
                "panels": [
                    {"id": 1, "title": "CPU", "type": "timeseries"},
                    {"id": 2, "title": "Memory", "type": "gauge"},
                ],
                "templating": {"list": [{"name": "host"}]},
                "time": {"from": "now-1h", "to": "now"},
            },
            "meta": {"folderUid": "fld1", "folderTitle": "Infra"},
        }
        respx.get(f"{BASE_URL}/api/dashboards/uid/abc123").mock(
            return_value=httpx.Response(200, json=dashboard_payload)
        )
        result = await call_tool("get_dashboard_summary", {"uid": "abc123"})
        summary = json_of(result)
        assert summary["panel_count"] == 2
        assert summary["variable_count"] == 1
        assert "timeseries" in summary["panel_types"]
        assert summary["folder_uid"] == "fld1"
        # Should NOT contain the full panel JSON
        assert "targets" not in str(summary)

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_dashboard_panel_queries(self):
        dashboard_payload = {
            "dashboard": {
                "uid": "abc123",
                "panels": [
                    {
                        "id": 1, "title": "CPU", "type": "timeseries",
                        "datasource": {"uid": "prom-uid", "type": "prometheus"},
                        "targets": [{"expr": "rate(cpu_seconds_total[5m])", "refId": "A"}],
                    }
                ],
            },
            "meta": {},
        }
        respx.get(f"{BASE_URL}/api/dashboards/uid/abc123").mock(
            return_value=httpx.Response(200, json=dashboard_payload)
        )
        result = await call_tool("get_dashboard_panel_queries", {"uid": "abc123"})
        panels = json_of(result)
        assert panels[0]["panel_id"] == 1
        assert panels[0]["datasource_uid"] == "prom-uid"
        assert panels[0]["targets"][0]["expr"] == "rate(cpu_seconds_total[5m])"

    @respx.mock
    @pytest.mark.asyncio
    async def test_create_dashboard(self):
        respx.post(f"{BASE_URL}/api/dashboards/db").mock(
            return_value=httpx.Response(200, json={"uid": "new_uid", "status": "success", "version": 1})
        )
        dash_json = json.dumps({"title": "New Dashboard", "panels": []})
        result = await call_tool("create_dashboard", {"dashboard_json": dash_json})
        data = json_of(result)
        assert data["uid"] == "new_uid"

    @respx.mock
    @pytest.mark.asyncio
    async def test_delete_dashboard(self):
        respx.delete(f"{BASE_URL}/api/dashboards/uid/abc123").mock(
            return_value=httpx.Response(200, json={"title": "Test", "message": "Dashboard Test deleted"})
        )
        result = await call_tool("delete_dashboard", {"uid": "abc123"})
        data = json_of(result)
        assert "deleted" in data["message"].lower()


# ---------------------------------------------------------------------------
# ── Datasource tools ──────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestDatasourceTools:

    @respx.mock
    @pytest.mark.asyncio
    async def test_list_datasources(self):
        respx.get(f"{BASE_URL}/api/datasources").mock(
            return_value=httpx.Response(200, json=[
                {"id": 1, "uid": "prom-uid", "name": "Prometheus", "type": "prometheus"}
            ])
        )
        result = await call_tool("list_datasources")
        data = json_of(result)
        assert data[0]["type"] == "prometheus"

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_datasource_by_uid(self):
        respx.get(f"{BASE_URL}/api/datasources/uid/prom-uid").mock(
            return_value=httpx.Response(200, json={"id": 1, "uid": "prom-uid", "name": "Prometheus"})
        )
        result = await call_tool("get_datasource", {"uid": "prom-uid"})
        data = json_of(result)
        assert data["uid"] == "prom-uid"

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_datasource_by_name(self):
        respx.get(f"{BASE_URL}/api/datasources/name/Prometheus").mock(
            return_value=httpx.Response(200, json={"id": 1, "uid": "prom-uid", "name": "Prometheus"})
        )
        result = await call_tool("get_datasource", {"name": "Prometheus"})
        data = json_of(result)
        assert data["name"] == "Prometheus"

    @pytest.mark.asyncio
    async def test_get_datasource_missing_args(self):
        result = await call_tool("get_datasource", {})
        data = json_of(result)
        assert "error" in data


# ---------------------------------------------------------------------------
# ── Folder tools ─────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestFolderTools:

    @respx.mock
    @pytest.mark.asyncio
    async def test_list_folders(self):
        respx.get(f"{BASE_URL}/api/folders").mock(
            return_value=httpx.Response(200, json=[{"id": 1, "uid": "fld1", "title": "Infra"}])
        )
        result = await call_tool("list_folders")
        data = json_of(result)
        assert data[0]["title"] == "Infra"

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_folder(self):
        respx.get(f"{BASE_URL}/api/folders/fld1").mock(
            return_value=httpx.Response(200, json={"id": 1, "uid": "fld1", "title": "Infra"})
        )
        result = await call_tool("get_folder", {"uid": "fld1"})
        data = json_of(result)
        assert data["uid"] == "fld1"

    @respx.mock
    @pytest.mark.asyncio
    async def test_create_folder(self):
        respx.post(f"{BASE_URL}/api/folders").mock(
            return_value=httpx.Response(200, json={"id": 2, "uid": "fld2", "title": "Monitoring"})
        )
        result = await call_tool("create_folder", {"title": "Monitoring", "uid": "fld2"})
        data = json_of(result)
        assert data["title"] == "Monitoring"

    @respx.mock
    @pytest.mark.asyncio
    async def test_delete_folder(self):
        respx.delete(f"{BASE_URL}/api/folders/fld1").mock(
            return_value=httpx.Response(200, json={"id": 1, "title": "Infra"})
        )
        result = await call_tool("delete_folder", {"uid": "fld1"})
        data = json_of(result)
        assert data["id"] == 1


# ---------------------------------------------------------------------------
# ── Prometheus tools ──────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

PROM_UID = "prom-datasource-uid"
PROM_RESULT = {
    "status": "success",
    "data": {"resultType": "vector", "result": [{"metric": {}, "value": [1716000000, "42"]}]},
}


class TestPrometheusTools:

    @respx.mock
    @pytest.mark.asyncio
    async def test_query_prometheus_instant(self):
        respx.get(f"{BASE_URL}/api/datasources/proxy/uid/{PROM_UID}/api/v1/query").mock(
            return_value=httpx.Response(200, json=PROM_RESULT)
        )
        result = await call_tool("query_prometheus", {
            "datasource_uid": PROM_UID,
            "expr": "up",
            "query_type": "instant",
        })
        data = json_of(result)
        assert data["status"] == "success"

    @respx.mock
    @pytest.mark.asyncio
    async def test_query_prometheus_range(self):
        range_result = {
            "status": "success",
            "data": {"resultType": "matrix", "result": []},
        }
        route = respx.get(
            f"{BASE_URL}/api/datasources/proxy/uid/{PROM_UID}/api/v1/query_range"
        ).mock(return_value=httpx.Response(200, json=range_result))
        await call_tool("query_prometheus", {
            "datasource_uid": PROM_UID,
            "expr": "rate(requests_total[5m])",
            "query_type": "range",
            "start": 1716000000,
            "end": 1716003600,
            "step": "60",
        })
        params = dict(route.calls.last.request.url.params)
        assert params["query"] == "rate(requests_total[5m])"
        assert params["step"] == "60"

    @respx.mock
    @pytest.mark.asyncio
    async def test_list_prometheus_metric_names(self):
        respx.get(
            f"{BASE_URL}/api/datasources/proxy/uid/{PROM_UID}/api/v1/label/__name__/values"
        ).mock(return_value=httpx.Response(200, json={"status": "success", "data": ["up", "go_goroutines"]}))
        result = await call_tool("list_prometheus_metric_names", {"datasource_uid": PROM_UID})
        data = json_of(result)
        assert "up" in data["data"]

    @respx.mock
    @pytest.mark.asyncio
    async def test_list_prometheus_label_names(self):
        respx.get(
            f"{BASE_URL}/api/datasources/proxy/uid/{PROM_UID}/api/v1/labels"
        ).mock(return_value=httpx.Response(200, json={"status": "success", "data": ["job", "instance"]}))
        result = await call_tool("list_prometheus_label_names", {"datasource_uid": PROM_UID})
        data = json_of(result)
        assert "job" in data["data"]

    @respx.mock
    @pytest.mark.asyncio
    async def test_list_prometheus_label_values(self):
        respx.get(
            f"{BASE_URL}/api/datasources/proxy/uid/{PROM_UID}/api/v1/label/job/values"
        ).mock(return_value=httpx.Response(200, json={"status": "success", "data": ["prometheus", "node"]}))
        result = await call_tool("list_prometheus_label_values", {
            "datasource_uid": PROM_UID,
            "label_name": "job",
        })
        data = json_of(result)
        assert "prometheus" in data["data"]


# ---------------------------------------------------------------------------
# ── Loki tools ───────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

LOKI_UID = "loki-datasource-uid"
LOKI_LOG_RESULT = {
    "status": "200 OK",
    "data": {
        "resultType": "streams",
        "result": [{"stream": {"job": "app"}, "values": [["1716000000000000000", "error occurred"]]}],
    },
}


class TestLokiTools:

    @respx.mock
    @pytest.mark.asyncio
    async def test_query_loki_logs(self):
        route = respx.get(
            f"{BASE_URL}/api/datasources/proxy/uid/{LOKI_UID}/loki/api/v1/query_range"
        ).mock(return_value=httpx.Response(200, json=LOKI_LOG_RESULT))
        result = await call_tool("query_loki_logs", {
            "datasource_uid": LOKI_UID,
            "query": '{job="app"} |= "error"',
            "limit": 50,
        })
        data = json_of(result)
        assert data["data"]["resultType"] == "streams"
        params = dict(route.calls.last.request.url.params)
        assert params["limit"] == "50"
        assert params["direction"] == "backward"

    @respx.mock
    @pytest.mark.asyncio
    async def test_list_loki_label_names(self):
        respx.get(
            f"{BASE_URL}/api/datasources/proxy/uid/{LOKI_UID}/loki/api/v1/labels"
        ).mock(return_value=httpx.Response(200, json={"status": "200 OK", "data": ["job", "namespace"]}))
        result = await call_tool("list_loki_label_names", {"datasource_uid": LOKI_UID})
        data = json_of(result)
        assert "job" in data["data"]

    @respx.mock
    @pytest.mark.asyncio
    async def test_list_loki_label_values(self):
        respx.get(
            f"{BASE_URL}/api/datasources/proxy/uid/{LOKI_UID}/loki/api/v1/label/job/values"
        ).mock(return_value=httpx.Response(200, json={"status": "200 OK", "data": ["app", "nginx"]}))
        result = await call_tool("list_loki_label_values", {
            "datasource_uid": LOKI_UID,
            "label_name": "job",
        })
        data = json_of(result)
        assert "app" in data["data"]

    @respx.mock
    @pytest.mark.asyncio
    async def test_query_loki_stats(self):
        respx.get(
            f"{BASE_URL}/api/datasources/proxy/uid/{LOKI_UID}/loki/api/v1/series"
        ).mock(return_value=httpx.Response(200, json={
            "data": [{"job": "app", "namespace": "default"}]
        }))
        result = await call_tool("query_loki_stats", {
            "datasource_uid": LOKI_UID,
            "query": '{job="app"}',
        })
        data = json_of(result)
        assert isinstance(data["data"], list)


# ---------------------------------------------------------------------------
# ── Alerting tools ────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

ALERT_RULE = {
    "uid": "alert-uid-1",
    "title": "High CPU",
    "folderUID": "fld1",
    "ruleGroup": "system",
    "condition": "A",
    "data": [],
    "noDataState": "NoData",
    "execErrState": "Error",
}


class TestAlertingTools:

    @respx.mock
    @pytest.mark.asyncio
    async def test_list_alerts(self):
        respx.get(f"{BASE_URL}/api/v1/provisioning/alert-rules").mock(
            return_value=httpx.Response(200, json=[ALERT_RULE])
        )
        result = await call_tool("list_alerts")
        data = json_of(result)
        assert data[0]["uid"] == "alert-uid-1"

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_alert_rule(self):
        respx.get(f"{BASE_URL}/api/v1/provisioning/alert-rules/alert-uid-1").mock(
            return_value=httpx.Response(200, json=ALERT_RULE)
        )
        result = await call_tool("get_alert_rule", {"uid": "alert-uid-1"})
        data = json_of(result)
        assert data["title"] == "High CPU"

    @respx.mock
    @pytest.mark.asyncio
    async def test_create_alert_rule(self):
        route = respx.post(f"{BASE_URL}/api/v1/provisioning/alert-rules").mock(
            return_value=httpx.Response(201, json={**ALERT_RULE, "uid": "new-uid"})
        )
        await call_tool("create_alert_rule", {"rule_json": json.dumps(ALERT_RULE)})
        body = json.loads(route.calls.last.request.content)
        assert body["title"] == "High CPU"

    @respx.mock
    @pytest.mark.asyncio
    async def test_update_alert_rule(self):
        updated = {**ALERT_RULE, "title": "Very High CPU"}
        route = respx.put(f"{BASE_URL}/api/v1/provisioning/alert-rules/alert-uid-1").mock(
            return_value=httpx.Response(200, json=updated)
        )
        await call_tool("update_alert_rule", {
            "uid": "alert-uid-1",
            "rule_json": json.dumps(updated),
        })
        body = json.loads(route.calls.last.request.content)
        assert body["title"] == "Very High CPU"

    @respx.mock
    @pytest.mark.asyncio
    async def test_delete_alert_rule_204(self):
        respx.delete(f"{BASE_URL}/api/v1/provisioning/alert-rules/alert-uid-1").mock(
            return_value=httpx.Response(204, content=b"")
        )
        result = await call_tool("delete_alert_rule", {"uid": "alert-uid-1"})
        data = json_of(result)
        assert data.get("status") == "deleted"

    @respx.mock
    @pytest.mark.asyncio
    async def test_list_contact_points(self):
        respx.get(f"{BASE_URL}/api/v1/provisioning/contact-points").mock(
            return_value=httpx.Response(200, json=[{"uid": "cp1", "name": "Slack", "type": "slack"}])
        )
        result = await call_tool("list_contact_points")
        data = json_of(result)
        assert data[0]["name"] == "Slack"

    @respx.mock
    @pytest.mark.asyncio
    async def test_list_notification_policies(self):
        respx.get(f"{BASE_URL}/api/v1/provisioning/policies").mock(
            return_value=httpx.Response(200, json={"receiver": "default", "routes": []})
        )
        result = await call_tool("list_notification_policies")
        data = json_of(result)
        assert data["receiver"] == "default"


# ---------------------------------------------------------------------------
# ── Annotation tools ──────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestAnnotationTools:

    @respx.mock
    @pytest.mark.asyncio
    async def test_list_annotations(self):
        respx.get(f"{BASE_URL}/api/annotations").mock(
            return_value=httpx.Response(200, json=[
                {"id": 1, "text": "Deploy v1.2", "time": 1716000000000, "tags": ["deploy"]}
            ])
        )
        result = await call_tool("list_annotations", {"limit": 50})
        data = json_of(result)
        assert data[0]["id"] == 1

    @respx.mock
    @pytest.mark.asyncio
    async def test_list_annotations_with_filters(self):
        route = respx.get(f"{BASE_URL}/api/annotations").mock(
            return_value=httpx.Response(200, json=[])
        )
        await call_tool("list_annotations", {
            "from_ms": 1716000000000,
            "to_ms": 1716003600000,
            "dashboard_uid": "abc123",
        })
        params = dict(route.calls.last.request.url.params)
        assert params["dashboardUID"] == "abc123"
        assert params["from"] == "1716000000000"

    @respx.mock
    @pytest.mark.asyncio
    async def test_create_annotation(self):
        route = respx.post(f"{BASE_URL}/api/annotations").mock(
            return_value=httpx.Response(200, json={"id": 42, "message": "Annotation added"})
        )
        await call_tool("create_annotation", {
            "text": "Deploy v1.3",
            "dashboard_uid": "abc123",
            "tags": ["deploy", "v1.3"],
            "time_ms": 1716000500000,
        })
        body = json.loads(route.calls.last.request.content)
        assert body["text"] == "Deploy v1.3"
        assert body["tags"] == ["deploy", "v1.3"]

    @respx.mock
    @pytest.mark.asyncio
    async def test_update_annotation(self):
        route = respx.patch(f"{BASE_URL}/api/annotations/42").mock(
            return_value=httpx.Response(200, json={"message": "Annotation patched"})
        )
        await call_tool("update_annotation", {
            "annotation_id": 42,
            "text": "Deploy v1.3 fixed",
        })
        body = json.loads(route.calls.last.request.content)
        assert body["text"] == "Deploy v1.3 fixed"

    @respx.mock
    @pytest.mark.asyncio
    async def test_delete_annotation(self):
        respx.delete(f"{BASE_URL}/api/annotations/42").mock(
            return_value=httpx.Response(200, json={"message": "Annotation deleted"})
        )
        result = await call_tool("delete_annotation", {"annotation_id": 42})
        data = json_of(result)
        assert "deleted" in data["message"].lower()

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_annotation_tags(self):
        respx.get(f"{BASE_URL}/api/annotations/tags").mock(
            return_value=httpx.Response(200, json={
                "result": {"tags": [{"tag": "deploy", "count": 5}]},
                "totalCount": 1,
            })
        )
        result = await call_tool("get_annotation_tags", {"limit": 20})
        data = json_of(result)
        assert data["totalCount"] == 1


# ---------------------------------------------------------------------------
# ── Admin tools ───────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestAdminTools:

    @respx.mock
    @pytest.mark.asyncio
    async def test_list_users(self):
        respx.get(f"{BASE_URL}/api/users").mock(
            return_value=httpx.Response(200, json=[
                {"id": 1, "login": "admin", "email": "admin@example.com", "isAdmin": True}
            ])
        )
        result = await call_tool("list_users")
        data = json_of(result)
        assert data[0]["login"] == "admin"

    @respx.mock
    @pytest.mark.asyncio
    async def test_list_users_with_query(self):
        route = respx.get(f"{BASE_URL}/api/users").mock(
            return_value=httpx.Response(200, json=[])
        )
        await call_tool("list_users", {"query": "alice", "page": 2, "perpage": 25})
        params = dict(route.calls.last.request.url.params)
        assert params["query"] == "alice"
        assert params["page"] == "2"
        assert params["perpage"] == "25"

    @respx.mock
    @pytest.mark.asyncio
    async def test_list_teams(self):
        respx.get(f"{BASE_URL}/api/teams/search").mock(
            return_value=httpx.Response(200, json={
                "teams": [{"id": 1, "orgId": 1, "name": "Ops", "memberCount": 3}],
                "totalCount": 1,
            })
        )
        result = await call_tool("list_teams")
        data = json_of(result)
        assert data["teams"][0]["name"] == "Ops"

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_org(self):
        respx.get(f"{BASE_URL}/api/org").mock(
            return_value=httpx.Response(200, json={"id": 1, "name": "Main Org."})
        )
        result = await call_tool("get_org")
        data = json_of(result)
        assert data["name"] == "Main Org."


# ---------------------------------------------------------------------------
# ── Navigation / deeplink tool ────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestGenerateDeeplink:

    @pytest.mark.asyncio
    async def test_dashboard_link(self):
        result = await call_tool("generate_deeplink", {
            "resource_type": "dashboard",
            "uid": "my-dash",
        })
        assert text_of(result) == f"{BASE_URL}/d/my-dash"

    @pytest.mark.asyncio
    async def test_dashboard_link_with_time_range(self):
        result = await call_tool("generate_deeplink", {
            "resource_type": "dashboard",
            "uid": "my-dash",
            "from_time": "now-6h",
            "to_time": "now",
        })
        url = text_of(result)
        assert "from=now-6h" in url
        assert "to=now" in url

    @pytest.mark.asyncio
    async def test_panel_link(self):
        result = await call_tool("generate_deeplink", {
            "resource_type": "panel",
            "uid": "my-dash",
            "panel_id": 5,
        })
        url = text_of(result)
        assert f"{BASE_URL}/d/my-dash" in url
        assert "viewPanel=5" in url

    @pytest.mark.asyncio
    async def test_explore_link(self):
        result = await call_tool("generate_deeplink", {
            "resource_type": "explore",
            "datasource_uid": "prom-uid",
            "query": "up",
        })
        url = text_of(result)
        assert f"{BASE_URL}/explore" in url
        assert "prom-uid" in url

    @pytest.mark.asyncio
    async def test_folder_link(self):
        result = await call_tool("generate_deeplink", {
            "resource_type": "folder",
            "uid": "fld1",
        })
        assert text_of(result) == f"{BASE_URL}/dashboards/f/fld1"

    @pytest.mark.asyncio
    async def test_alerting_link(self):
        result = await call_tool("generate_deeplink", {"resource_type": "alerting"})
        assert text_of(result) == f"{BASE_URL}/alerting"

    @pytest.mark.asyncio
    async def test_unknown_resource_type_returns_error(self):
        result = await call_tool("generate_deeplink", {"resource_type": "invalid_type"})
        data = json_of(result)
        assert "error" in data


# ---------------------------------------------------------------------------
# ── HTTP error handling ───────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestHTTPErrorHandling:

    @respx.mock
    @pytest.mark.asyncio
    async def test_401_returns_error_json(self):
        respx.get(f"{BASE_URL}/api/health").mock(
            return_value=httpx.Response(401, json={"message": "Unauthorized"})
        )
        result = await call_tool("health_check")
        data = json_of(result)
        assert "error" in data
        assert "401" in data["error"]

    @respx.mock
    @pytest.mark.asyncio
    async def test_404_returns_error_json(self):
        respx.get(f"{BASE_URL}/api/dashboards/uid/nonexistent").mock(
            return_value=httpx.Response(404, json={"message": "Dashboard not found"})
        )
        result = await call_tool("get_dashboard", {"uid": "nonexistent"})
        data = json_of(result)
        assert "error" in data
        assert "404" in data["error"]

    @respx.mock
    @pytest.mark.asyncio
    async def test_500_returns_error_json(self):
        respx.get(f"{BASE_URL}/api/datasources").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        result = await call_tool("list_datasources")
        data = json_of(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_unknown_tool_raises(self):
        from grafana_mcp.server import call_tool as server_call_tool
        with pytest.raises(ValueError, match="Unknown tool"):
            await server_call_tool("nonexistent_tool", {})


# ---------------------------------------------------------------------------
# ── Security tests ────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestSecurity:

    @respx.mock
    @pytest.mark.asyncio
    async def test_api_token_in_authorization_header_not_in_response(self):
        """Token must be sent as header value — never echoed in the tool output."""
        respx.get(f"{BASE_URL}/api/health").mock(
            return_value=httpx.Response(200, json={"database": "ok"})
        )
        result = await call_tool("health_check")
        output_text = text_of(result)
        assert TEST_TOKEN not in output_text

    @respx.mock
    @pytest.mark.asyncio
    async def test_bearer_token_format(self):
        route = respx.get(f"{BASE_URL}/api/health").mock(
            return_value=httpx.Response(200, json={"database": "ok"})
        )
        await call_tool("health_check")
        auth = route.calls.last.request.headers["Authorization"]
        assert auth.startswith("Bearer ")
        assert TEST_TOKEN in auth

    @respx.mock
    @pytest.mark.asyncio
    async def test_ssl_verify_true_by_default(self, client):
        """SSL verification must be enabled by default."""
        assert client._verify is True

    @respx.mock
    @pytest.mark.asyncio
    async def test_ssl_verify_false_user_opt_in(self):
        s = make_settings(ssl_verify=False)
        with patch("grafana_mcp.client.get_settings", return_value=s):
            c = GrafanaClient()
        assert c._verify is False

    def test_settings_token_not_in_repr(self):
        """Settings repr must not expose the token."""
        s = make_settings()
        assert TEST_TOKEN not in repr(s)

    @pytest.mark.asyncio
    async def test_tool_accepts_no_plaintext_credentials_in_output(self):
        """generate_deeplink does not include credentials in the URL."""
        result = await call_tool("generate_deeplink", {
            "resource_type": "dashboard",
            "uid": "dash1",
        })
        assert TEST_TOKEN not in text_of(result)


# ---------------------------------------------------------------------------
# ── Config resolution tests ───────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestConfigResolution:

    def test_env_var_url_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("GRAFANA_URL", "http://env-grafana.test")
        monkeypatch.setenv("GRAFANA_TOKEN", "env-token")
        # Clear lru_cache so we pick up the new env vars
        from grafana_mcp.config import get_settings as _gs
        _gs.cache_clear()
        try:
            with patch("grafana_mcp.config.retrieve_secret", return_value=None):
                with patch("grafana_mcp.config._load_yaml_config", return_value={}):
                    s = _gs()
                    assert s.grafana_url == "http://env-grafana.test"
                    assert s.api_token == "env-token"
        finally:
            _gs.cache_clear()

    def test_ssl_verify_env_false(self, monkeypatch):
        monkeypatch.setenv("GRAFANA_URL", "http://x.test")
        monkeypatch.setenv("GRAFANA_TOKEN", "tok")
        monkeypatch.setenv("GRAFANA_SSL_VERIFY", "false")
        from grafana_mcp.config import get_settings as _gs
        _gs.cache_clear()
        try:
            with patch("grafana_mcp.config.retrieve_secret", return_value=None):
                with patch("grafana_mcp.config._load_yaml_config", return_value={}):
                    s = _gs()
                    assert s.ssl_verify is False
        finally:
            _gs.cache_clear()

    def test_missing_url_raises(self):
        from grafana_mcp.config import get_settings as _gs
        _gs.cache_clear()
        try:
            with patch("grafana_mcp.config.retrieve_secret", return_value=None):
                with patch("grafana_mcp.config._load_yaml_config", return_value={}):
                    with patch.dict(os.environ, {}, clear=True):
                        # Ensure GRAFANA_URL and GRAFANA_TOKEN not in env
                        env = {k: v for k, v in os.environ.items()
                               if k not in ("GRAFANA_URL", "GRAFANA_TOKEN")}
                        with patch.dict(os.environ, env, clear=True):
                            with pytest.raises(RuntimeError, match="Grafana URL"):
                                _gs()
        finally:
            _gs.cache_clear()


# ---------------------------------------------------------------------------
# ── List tools coverage test ──────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class TestListToolsCoverage:

    @pytest.mark.asyncio
    async def test_all_37_tools_registered(self):
        from grafana_mcp.server import _HANDLERS, list_tools
        tools = await list_tools()
        tool_names = {t.name for t in tools}
        handler_names = set(_HANDLERS.keys())

        # Every handler must have a corresponding tool schema
        assert handler_names == tool_names, (
            f"Mismatch: handlers only: {handler_names - tool_names}, "
            f"tools only: {tool_names - handler_names}"
        )
        assert len(tools) == 37, f"Expected 37 tools, got {len(tools)}"

    @pytest.mark.asyncio
    async def test_all_tool_schemas_have_required_fields(self):
        from grafana_mcp.server import list_tools
        tools = await list_tools()
        for tool in tools:
            assert tool.name, f"Tool missing name: {tool}"
            assert tool.description, f"Tool '{tool.name}' missing description"
            assert "type" in tool.inputSchema, f"Tool '{tool.name}' inputSchema missing 'type'"
