"""
Async Proxmox VE API client.

Authentication uses Proxmox API tokens sent via the Authorization header:
  Authorization: PVEAPIToken=user@realm!tokenid=uuid

API tokens do NOT need CSRF tokens for POST/PUT/DELETE — only session tickets do.
All responses from Proxmox are wrapped in {"data": ...}; this client unwraps them.
All methods raise ``ProxmoxAPIError`` on non-2xx responses.
"""
from __future__ import annotations

import time
from typing import Any, Optional

import httpx
import structlog

from proxmox_mcp.config import Settings

log = structlog.get_logger(__name__)


class ProxmoxAPIError(Exception):
    """Raised for non-2xx Proxmox API responses."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"Proxmox API error {status_code}: {message}")


class ProxmoxClient:
    """Async context-manager wrapper around the Proxmox VE REST API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Proxmox API base path — reverse proxy strips the port, path stays
        self._base_url = settings.proxmox_url.rstrip("/") + "/api2/json/"
        self._headers = {
            "Authorization": f"PVEAPIToken={settings.api_token}",
            "Accept": "application/json",
        }
        self._client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "ProxmoxClient":
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
            raise RuntimeError("ProxmoxClient must be used as an async context manager")
        return self._client

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Make a request and unwrap the Proxmox ``{"data": ...}`` envelope."""
        client = self._client_or_raise()
        t0 = time.monotonic()
        response = await client.request(method, path, **kwargs)
        elapsed = round((time.monotonic() - t0) * 1000)

        log.info(
            "proxmox.api_call",
            method=method,
            path=path,
            status=response.status_code,
            elapsed_ms=elapsed,
        )

        if response.status_code == 401:
            raise ProxmoxAPIError(401, "Unauthorized — check your API token (format: user@realm!tokenid=uuid)")
        if response.status_code == 403:
            raise ProxmoxAPIError(403, "Forbidden — token lacks permission for this operation")
        if response.status_code == 404:
            raise ProxmoxAPIError(404, f"Not found: {path}")
        if response.status_code == 500:
            body = response.text[:500]
            raise ProxmoxAPIError(500, f"Proxmox internal error: {body}")
        if not response.is_success:
            body = response.text[:500]
            raise ProxmoxAPIError(response.status_code, body)

        if not response.content:
            return None

        payload = response.json()
        # Proxmox always wraps in {"data": ...}
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    async def _get(self, path: str, **params: Any) -> Any:
        return await self._request("GET", path, params=params or None)

    async def _post(self, path: str, **data: Any) -> Any:
        return await self._request("POST", path, data=data or None)

    # ------------------------------------------------------------------
    # Version / health
    # ------------------------------------------------------------------

    async def get_version(self) -> dict[str, Any]:
        """Return Proxmox VE version information."""
        result = await self._get("version")
        return result or {}

    # ------------------------------------------------------------------
    # Cluster
    # ------------------------------------------------------------------

    async def get_cluster_status(self) -> list[dict[str, Any]]:
        """Return cluster status (nodes and quorum info)."""
        result = await self._get("cluster/status")
        return result or []

    async def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent cluster-wide tasks."""
        result = await self._get("cluster/tasks")
        tasks = result or []
        return tasks[:limit]

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    async def list_nodes(self) -> list[dict[str, Any]]:
        """Return all nodes in the cluster."""
        result = await self._get("nodes")
        return result or []

    async def get_node_status(self, node: str) -> dict[str, Any]:
        """Return detailed status and resource usage for a node."""
        result = await self._get(f"nodes/{node}/status")
        return result or {}

    # ------------------------------------------------------------------
    # QEMU Virtual Machines
    # ------------------------------------------------------------------

    async def list_vms(self, node: str) -> list[dict[str, Any]]:
        """Return all QEMU VMs on a node."""
        result = await self._get(f"nodes/{node}/qemu")
        return result or []

    async def get_vm_status(self, node: str, vmid: int) -> dict[str, Any]:
        """Return current status of a QEMU VM."""
        result = await self._get(f"nodes/{node}/qemu/{vmid}/status/current")
        return result or {}

    async def start_vm(self, node: str, vmid: int) -> Any:
        """Start a QEMU VM. Returns a task UPID."""
        return await self._post(f"nodes/{node}/qemu/{vmid}/status/start")

    async def stop_vm(self, node: str, vmid: int) -> Any:
        """Force-stop a QEMU VM (like pulling the power). Returns a task UPID."""
        return await self._post(f"nodes/{node}/qemu/{vmid}/status/stop")

    async def shutdown_vm(self, node: str, vmid: int, timeout: int = 60) -> Any:
        """Gracefully shut down a QEMU VM (ACPI). Returns a task UPID."""
        return await self._request(
            "POST",
            f"nodes/{node}/qemu/{vmid}/status/shutdown",
            data={"timeout": timeout},
        )

    async def reboot_vm(self, node: str, vmid: int) -> Any:
        """Reboot a QEMU VM. Returns a task UPID."""
        return await self._post(f"nodes/{node}/qemu/{vmid}/status/reboot")

    # ------------------------------------------------------------------
    # LXC Containers
    # ------------------------------------------------------------------

    async def list_lxc(self, node: str) -> list[dict[str, Any]]:
        """Return all LXC containers on a node."""
        result = await self._get(f"nodes/{node}/lxc")
        return result or []

    async def get_lxc_status(self, node: str, vmid: int) -> dict[str, Any]:
        """Return current status of an LXC container."""
        result = await self._get(f"nodes/{node}/lxc/{vmid}/status/current")
        return result or {}

    async def start_lxc(self, node: str, vmid: int) -> Any:
        """Start an LXC container. Returns a task UPID."""
        return await self._post(f"nodes/{node}/lxc/{vmid}/status/start")

    async def stop_lxc(self, node: str, vmid: int) -> Any:
        """Force-stop an LXC container. Returns a task UPID."""
        return await self._post(f"nodes/{node}/lxc/{vmid}/status/stop")

    async def shutdown_lxc(self, node: str, vmid: int, timeout: int = 60) -> Any:
        """Gracefully shut down an LXC container. Returns a task UPID."""
        return await self._request(
            "POST",
            f"nodes/{node}/lxc/{vmid}/status/shutdown",
            data={"timeout": timeout},
        )

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    async def list_storages(self, node: str) -> list[dict[str, Any]]:
        """Return all storage pools available on a node."""
        result = await self._get(f"nodes/{node}/storage")
        return result or []

    async def get_storage_content(self, node: str, storage: str) -> list[dict[str, Any]]:
        """Return contents (ISOs, templates, backups, VM disks) of a storage pool."""
        result = await self._get(f"nodes/{node}/storage/{storage}/content")
        return result or []
