"""
Async Portainer API client.

Uses httpx for async HTTP with Bearer / API-Key authentication.
Portainer Access Tokens (ptr_…) are sent via the X-API-Key header.
JWT tokens are sent via Authorization: Bearer.

All methods raise ``PortainerAPIError`` on non-2xx responses.
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional
from urllib.parse import urljoin

import httpx
import structlog

from portainer_mcp.config import Settings

log = structlog.get_logger(__name__)


class PortainerAPIError(Exception):
    """Raised for non-2xx Portainer API responses."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"Portainer API error {status_code}: {message}")


def _build_headers(token: str) -> dict[str, str]:
    """Choose the correct auth header based on token format."""
    if token.startswith("ptr_"):
        return {"X-API-Key": token}
    return {"Authorization": f"Bearer {token}"}


class PortainerClient:
    """Async context-manager wrapper around the Portainer REST API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = settings.portainer_url.rstrip("/") + "/api/"
        self._headers = {
            **_build_headers(settings.api_token),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "PortainerClient":
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            verify=self._settings.ssl_verify,
            timeout=self._settings.timeout,
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _client_or_raise(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("PortainerClient must be used as an async context manager")
        return self._client

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        client = self._client_or_raise()
        t0 = time.monotonic()
        response = await client.request(method, path, **kwargs)
        elapsed = round((time.monotonic() - t0) * 1000)

        log.info(
            "portainer.api_call",
            method=method,
            path=path,
            status=response.status_code,
            elapsed_ms=elapsed,
        )

        if response.status_code == 401:
            raise PortainerAPIError(401, "Unauthorized — check your API token")
        if response.status_code == 403:
            raise PortainerAPIError(403, "Forbidden — insufficient permissions")
        if response.status_code == 404:
            raise PortainerAPIError(404, f"Not found: {path}")
        if not response.is_success:
            body = response.text[:500]
            raise PortainerAPIError(response.status_code, body)

        if not response.content:
            return None
        return response.json()

    # ------------------------------------------------------------------
    # Endpoints (environments)
    # ------------------------------------------------------------------

    async def list_endpoints(self) -> list[dict[str, Any]]:
        """Return all endpoints (Portainer environments)."""
        return await self._request("GET", "endpoints")  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Containers
    # ------------------------------------------------------------------

    async def list_containers(self, endpoint_id: int) -> list[dict[str, Any]]:
        """List all containers on an endpoint (includes stopped)."""
        return await self._request(
            "GET",
            f"endpoints/{endpoint_id}/docker/containers/json",
            params={"all": "true"},
        )  # type: ignore[return-value]

    async def inspect_container(self, endpoint_id: int, container_id: str) -> dict[str, Any]:
        """Return full container inspection data."""
        return await self._request(
            "GET",
            f"endpoints/{endpoint_id}/docker/containers/{container_id}/json",
        )  # type: ignore[return-value]

    async def start_container(self, endpoint_id: int, container_id: str) -> None:
        """Start a stopped container."""
        await self._request(
            "POST",
            f"endpoints/{endpoint_id}/docker/containers/{container_id}/start",
        )

    async def stop_container(self, endpoint_id: int, container_id: str) -> None:
        """Stop a running container."""
        await self._request(
            "POST",
            f"endpoints/{endpoint_id}/docker/containers/{container_id}/stop",
        )

    async def container_logs(
        self,
        endpoint_id: int,
        container_id: str,
        tail: int = 100,
        timestamps: bool = False,
    ) -> str:
        """Retrieve container logs as a string."""
        client = self._client_or_raise()
        t0 = time.monotonic()
        response = await client.get(
            f"endpoints/{endpoint_id}/docker/containers/{container_id}/logs",
            params={
                "stdout": "true",
                "stderr": "true",
                "tail": str(tail),
                "timestamps": "true" if timestamps else "false",
            },
        )
        elapsed = round((time.monotonic() - t0) * 1000)
        log.info("portainer.api_call", method="GET", path="container_logs", status=response.status_code, elapsed_ms=elapsed)
        if not response.is_success:
            raise PortainerAPIError(response.status_code, response.text[:500])
        return response.text

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------

    async def list_images(self, endpoint_id: int) -> list[dict[str, Any]]:
        """List all Docker images on an endpoint."""
        return await self._request(
            "GET",
            f"endpoints/{endpoint_id}/docker/images/json",
            params={"all": "false"},
        )  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Stacks
    # ------------------------------------------------------------------

    async def list_stacks(self) -> list[dict[str, Any]]:
        """List all stacks across all endpoints."""
        return await self._request("GET", "stacks")  # type: ignore[return-value]

    async def deploy_stack(
        self,
        endpoint_id: int,
        stack_name: str,
        compose_content: str,
        env_vars: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Deploy or update a Compose stack.

        Creates a new stack if *stack_name* does not exist, otherwise updates it.
        """
        # Check if a stack with this name already exists
        stacks = await self.list_stacks()
        existing = next((s for s in stacks if s.get("Name") == stack_name), None)

        env_list = [{"name": k, "value": v} for k, v in (env_vars or {}).items()]

        if existing:
            stack_id = existing["Id"]
            payload: dict[str, Any] = {
                "stackFileContent": compose_content,
                "env": env_list,
                "prune": False,
            }
            return await self._request(  # type: ignore[return-value]
                "PUT",
                f"stacks/{stack_id}",
                params={"endpointId": endpoint_id},
                content=json.dumps(payload),
            )

        payload = {
            "name": stack_name,
            "stackFileContent": compose_content,
            "env": env_list,
        }
        return await self._request(  # type: ignore[return-value]
            "POST",
            "stacks/create/standalone/string",
            params={"endpointId": endpoint_id},
            content=json.dumps(payload),
        )

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health(self) -> dict[str, Any]:
        """Check Portainer status endpoint."""
        return await self._request("GET", "status")  # type: ignore[return-value]
