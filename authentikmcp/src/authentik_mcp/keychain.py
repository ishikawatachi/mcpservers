"""macOS Keychain integration for Authentik MCP."""
from __future__ import annotations

import subprocess
from typing import Optional
import structlog

log = structlog.get_logger(__name__)
_SERVICE = "authentik-mcp"


def _run_security(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["/usr/bin/security", *args], capture_output=True, text=True, check=False)


def store_secret(account: str, value: str) -> None:
    _run_security("delete-generic-password", "-s", _SERVICE, "-a", account)
    result = _run_security("add-generic-password", "-s", _SERVICE, "-a", account, "-w", value)
    if result.returncode != 0:
        raise RuntimeError(f"Keychain store failed for '{account}': {result.stderr.strip()}")
    log.info("keychain.stored", account=account)


def retrieve_secret(account: str) -> Optional[str]:
    result = _run_security("find-generic-password", "-s", _SERVICE, "-a", account, "-w")
    if result.returncode != 0:
        log.debug("keychain.not_found", account=account)
        return None
    return result.stdout.strip() or None


def delete_secret(account: str) -> bool:
    result = _run_security("delete-generic-password", "-s", _SERVICE, "-a", account)
    deleted = result.returncode == 0
    log.info("keychain.deleted", account=account, success=deleted)
    return deleted
