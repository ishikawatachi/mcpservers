"""
Async HTTP client for the Grafana REST API.

All endpoints use: GET <grafana_url>/api/<path>
Authentication: Authorization: Bearer <token>
"""
from __future__ import annotations

import httpx
import structlog

from grafana_mcp.config import get_settings

log = structlog.get_logger(__name__)


class GrafanaClient:
    """Thin async wrapper around the Grafana HTTP API."""

    def __init__(self) -> None:
        cfg = get_settings()
        self._base = cfg.grafana_url
        self._headers = {"Authorization": f"Bearer {cfg.api_token}", "Accept": "application/json"}
        self._verify = cfg.ssl_verify
        self._timeout = cfg.timeout

    async def get(self, path: str, **params: str) -> dict | list:
        url = f"{self._base}/api/{path.lstrip('/')}"
        async with httpx.AsyncClient(verify=self._verify, timeout=self._timeout) as c:
            r = await c.get(url, headers=self._headers, params=params or None)
        r.raise_for_status()
        return r.json()

    async def post(self, path: str, body: dict) -> dict:
        url = f"{self._base}/api/{path.lstrip('/')}"
        headers = {**self._headers, "Content-Type": "application/json"}
        async with httpx.AsyncClient(verify=self._verify, timeout=self._timeout) as c:
            r = await c.post(url, headers=headers, json=body)
        r.raise_for_status()
        return r.json()

    async def put(self, path: str, body: dict) -> dict:
        url = f"{self._base}/api/{path.lstrip('/')}"
        headers = {**self._headers, "Content-Type": "application/json"}
        async with httpx.AsyncClient(verify=self._verify, timeout=self._timeout) as c:
            r = await c.put(url, headers=headers, json=body)
        r.raise_for_status()
        return r.json()

    async def delete(self, path: str) -> dict:
        url = f"{self._base}/api/{path.lstrip('/')}"
        async with httpx.AsyncClient(verify=self._verify, timeout=self._timeout) as c:
            r = await c.delete(url, headers=self._headers)
        r.raise_for_status()
        return r.json()
