"""
Async HTTP client for the Authentik REST API.

All endpoints use: GET <authentik_url>/api/v3/<path>
Authentication: Authorization: Bearer <token>
Swagger UI available at: <authentik_url>/api/v3/
"""
from __future__ import annotations

import httpx
import structlog

from authentik_mcp.config import get_settings

log = structlog.get_logger(__name__)


class AuthentikClient:
    """Thin async wrapper around the Authentik HTTP API."""

    def __init__(self) -> None:
        cfg = get_settings()
        self._base = cfg.authentik_url
        self._headers = {"Authorization": f"Bearer {cfg.api_token}", "Accept": "application/json"}
        self._verify = cfg.ssl_verify
        self._timeout = cfg.timeout

    async def get(self, path: str, **params: str) -> dict | list:
        url = f"{self._base}/api/v3/{path.lstrip('/')}"
        async with httpx.AsyncClient(verify=self._verify, timeout=self._timeout) as c:
            r = await c.get(url, headers=self._headers, params=params or None)
        r.raise_for_status()
        return r.json()

    async def post(self, path: str, body: dict) -> dict:
        url = f"{self._base}/api/v3/{path.lstrip('/')}"
        headers = {**self._headers, "Content-Type": "application/json"}
        async with httpx.AsyncClient(verify=self._verify, timeout=self._timeout) as c:
            r = await c.post(url, headers=headers, json=body)
        r.raise_for_status()
        return r.json()

    async def patch(self, path: str, body: dict) -> dict:
        url = f"{self._base}/api/v3/{path.lstrip('/')}"
        headers = {**self._headers, "Content-Type": "application/json"}
        async with httpx.AsyncClient(verify=self._verify, timeout=self._timeout) as c:
            r = await c.patch(url, headers=headers, json=body)
        r.raise_for_status()
        return r.json()

    async def delete(self, path: str) -> None:
        url = f"{self._base}/api/v3/{path.lstrip('/')}"
        async with httpx.AsyncClient(verify=self._verify, timeout=self._timeout) as c:
            r = await c.delete(url, headers=self._headers)
        r.raise_for_status()
