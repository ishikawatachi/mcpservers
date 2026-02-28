"""
macOS Keychain integration for secure token/URL storage.

Uses the `security` CLI tool (built into macOS) to store and retrieve
secrets without ever exposing them in plaintext to the process environment.
"""
from __future__ import annotations

import subprocess
import logging
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

_SERVICE = "proxmox-mcp"


def _run_security(*args: str) -> subprocess.CompletedProcess[str]:
    """Run a macOS `security` command and return the result."""
    return subprocess.run(
        ["/usr/bin/security", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def store_secret(account: str, value: str) -> None:
    """Store *value* in the macOS Keychain under *account*.

    If an entry already exists it is deleted first so `add-generic-password`
    succeeds cleanly.
    """
    _run_security("delete-generic-password", "-s", _SERVICE, "-a", account)

    result = _run_security(
        "add-generic-password",
        "-s", _SERVICE,
        "-a", account,
        "-w", value,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Keychain store failed for account '{account}': {result.stderr.strip()}"
        )
    log.info("keychain.stored", account=account)


def retrieve_secret(account: str) -> Optional[str]:
    """Retrieve the secret stored under *account* from the macOS Keychain.

    Returns ``None`` if the entry does not exist.
    """
    result = _run_security(
        "find-generic-password",
        "-s", _SERVICE,
        "-a", account,
        "-w",
    )
    if result.returncode != 0:
        log.debug("keychain.not_found", account=account)
        return None
    value = result.stdout.strip()
    log.info("keychain.retrieved", account=account)
    return value or None


def delete_secret(account: str) -> bool:
    """Delete a Keychain entry. Returns True if deleted, False if not found."""
    result = _run_security("delete-generic-password", "-s", _SERVICE, "-a", account)
    deleted = result.returncode == 0
    log.info("keychain.deleted", account=account, success=deleted)
    return deleted
