"""
Async Synology DSM WebAPI client.

Authentication uses a Personal Access Token (PAT) — available in DSM 7.2.2+.
The PAT is sent two ways for maximum compatibility:
  • HTTP header:  Authorization: Bearer <token>
  • Query param:  _sid=<token>  (required for older CGI endpoints like Storage.CGI)

All DSM responses are wrapped in {"success": true/false, "data": ...}.
This client unwraps the data and raises ``SynologyAPIError`` on errors.

DSM WebAPI base path:  https://NAS:PORT/webapi/
Dynamic path per API:  resolved via SYNO.API.Info discovery.

All endpoints support GET with query params; some also accept POST.
This client always uses GET for reads and POST only where DSM requires it.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

import httpx
import structlog

from synology_mcp.config import Settings

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Known static CGI paths for commonly used APIs
# (avoids a full discovery round-trip on every call)
# ---------------------------------------------------------------------------
_STATIC_CGI_MAP: Dict[str, Tuple[str, int]] = {
    # api_name -> (cgi_path, max_version)
    "SYNO.API.Info":                   ("query.cgi", 1),
    "SYNO.DSM.Info":                   ("entry.cgi", 1),
    "SYNO.Core.System.Utilization":    ("entry.cgi", 1),
    "SYNO.Storage.CGI.Storage":        ("storage.cgi", 1),
    "SYNO.Storage.CGI.HddMan":         ("storage.cgi", 1),
    "SYNO.Core.Share":                 ("entry.cgi", 1),
    "SYNO.Core.Package":               ("entry.cgi", 1),
    "SYNO.Core.TaskScheduler":         ("entry.cgi", 1),
    "SYNO.Docker.Container":           ("entry.cgi", 1),
    "SYNO.Docker.Image":               ("entry.cgi", 1),
    "SYNO.FileStation.Info":           ("entry.cgi", 2),
    "SYNO.FileStation.List":           ("entry.cgi", 2),
    "SYNO.Core.SecurityScan.Status":   ("entry.cgi", 1),
    "SYNO.Backup.Task":                ("entry.cgi", 1),
}


class SynologyAPIError(Exception):
    """Raised for DSM API errors (HTTP non-2xx or success=false)."""

    def __init__(self, status_code: int, message: str, error_code: Optional[int] = None) -> None:
        self.status_code = status_code
        self.error_code = error_code
        detail = f" (DSM error {error_code})" if error_code else ""
        super().__init__(f"Synology API error {status_code}{detail}: {message}")


# DSM error code → human-readable explanation
_DSM_ERROR_CODES: Dict[int, str] = {
    100: "Unknown error",
    101: "No parameter",
    102: "API does not exist",
    103: "Method does not exist",
    104: "Version does not support",
    105: "Insufficient user privilege",
    106: "Session timeout",
    107: "Session interrupted by duplicate login",
    119: "Insufficient user privilege for SID",
    120: "Invalid parameter",
    400: "Invalid parameter (FileStation)",
    401: "Unknown error (FileStation)",
    402: "No such file or directory",
    403: "Permission denied",
    404: "File upload failed",
    405: "Disk quota exceeded",
    406: "No space left on device",
    407: "Input/Output error",
    408: "Illegal name or path",
    409: "File exists",
    410: "Disk quota exceeded",
    411: "File size exceeds limit",
    412: "Remote connection failed",
}


def _dsm_error_message(code: int) -> str:
    return _DSM_ERROR_CODES.get(code, f"Unknown DSM error code {code}")


class SynologyClient:
    """Async context-manager wrapper around the Synology DSM WebAPI."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = settings.synology_url.rstrip("/") + "/webapi/"
        # PAT sent as Bearer header AND as _sid for CGI endpoints
        self._headers = {
            "Authorization": f"Bearer {settings.api_token}",
            "Accept": "application/json",
        }
        self._client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "SynologyClient":
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
            raise RuntimeError("SynologyClient must be used as an async context manager")
        return self._client

    async def _get(self, api: str, method: str, extra: Optional[Dict[str, Any]] = None) -> Any:
        """Perform a DSM WebAPI GET request and return the ``data`` payload.

        Resolves the CGI path from ``_STATIC_CGI_MAP`` (falls back to entry.cgi).
        Passes the PAT as both the Bearer header and ``_sid`` query parameter.
        """
        client = self._client_or_raise()
        cgi_path, version = _STATIC_CGI_MAP.get(api, ("entry.cgi", 1))

        params: Dict[str, Any] = {
            "api": api,
            "version": version,
            "method": method,
            "_sid": self._settings.api_token,  # CGI fallback for older APIs
        }
        if extra:
            params.update(extra)

        t0 = time.monotonic()
        response = await client.get(cgi_path, params=params)
        elapsed = round((time.monotonic() - t0) * 1000)

        log.info(
            "synology.api_call",
            api=api,
            method=method,
            status=response.status_code,
            elapsed_ms=elapsed,
        )

        # HTTP-level errors
        if response.status_code == 401:
            raise SynologyAPIError(401, "Unauthorized — check your Personal Access Token")
        if response.status_code == 403:
            raise SynologyAPIError(403, "Forbidden — token lacks permission for this operation")
        if response.status_code == 404:
            raise SynologyAPIError(404, f"Not found: {cgi_path}?api={api}")
        if not response.is_success:
            raise SynologyAPIError(response.status_code, response.text[:500])

        body = response.json()

        # DSM application-level errors
        if not body.get("success", False):
            err = body.get("error", {})
            code = err.get("code", 0)
            msg = _dsm_error_message(code)
            raise SynologyAPIError(200, msg, error_code=code)

        return body.get("data")

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    async def query_api_info(self) -> Any:
        """Query all available APIs — used for health check and API discovery."""
        return await self._get("SYNO.API.Info", "query", {"query": "all"})

    async def get_dsm_info(self) -> Any:
        """Return DSM system info: model, firmware version, serial, uptime."""
        return await self._get("SYNO.DSM.Info", "get")

    async def get_system_utilization(self) -> Any:
        """Return current CPU, memory, network, and disk I/O utilization."""
        return await self._get(
            "SYNO.Core.System.Utilization",
            "get",
            {"type": "current", "resource": "all"},
        )

    async def get_storage_info(self) -> Any:
        """Return storage pool, volume, and disk health overview."""
        return await self._get(
            "SYNO.Storage.CGI.Storage",
            "load_info",
            {"fetchBasic": "true", "limit": -1},
        )

    async def get_disk_info(self) -> Any:
        """Return per-disk details: model, temperature, S.M.A.R.T. status."""
        return await self._get(
            "SYNO.Storage.CGI.HddMan",
            "list",
            {"fetchAll": "true"},
        )

    async def list_shares(self) -> Any:
        """Return all shared folders with permissions and encryption status."""
        return await self._get(
            "SYNO.Core.Share",
            "list",
            {"limit": -1, "offset": 0, "additional": "recyclebin,share_quota,encrypted"},
        )

    async def list_packages(self) -> Any:
        """Return all installed packages and their running status."""
        return await self._get(
            "SYNO.Core.Package",
            "list",
            {"limit": -1, "additional": "description,status,startable"},
        )

    async def list_scheduled_tasks(self) -> Any:
        """Return all Task Scheduler tasks with last-run status."""
        return await self._get(
            "SYNO.Core.TaskScheduler",
            "list",
            {"additional": "task_setting,owner,real_owner,last_run_result"},
        )

    async def list_docker_containers(self) -> Any:
        """Return all Docker / Container Manager containers."""
        return await self._get(
            "SYNO.Docker.Container",
            "list",
            {"limit": -1, "offset": 0},
        )

    async def list_docker_images(self) -> Any:
        """Return all Docker images on the NAS."""
        return await self._get(
            "SYNO.Docker.Image",
            "list",
            {"limit": -1, "offset": 0},
        )

    async def list_files(
        self,
        folder_path: str,
        additional: Optional[str] = None,
    ) -> Any:
        """Return files and directories inside *folder_path* on the NAS.

        Args:
            folder_path: Absolute share path, e.g. ``/docker`` or ``/homes/admin``.
            additional:  Comma-separated extra fields: ``real_path,size,owner,time,perm,type``.
        """
        params: Dict[str, Any] = {
            "folder_path": folder_path,
            "limit": 100,
            "offset": 0,
            "sort_by": "name",
            "sort_direction": "ASC",
        }
        if additional:
            params["additional"] = additional
        return await self._get("SYNO.FileStation.List", "list", params)

    async def get_security_status(self) -> Any:
        """Return Security Advisor scan results."""
        return await self._get("SYNO.Core.SecurityScan.Status", "get")

    async def get_backup_tasks(self) -> Any:
        """Return Hyper Backup task status and last-run results."""
        return await self._get(
            "SYNO.Backup.Task",
            "list",
            {"additional": "last_bkp_result,schedule,extra"},
        )
