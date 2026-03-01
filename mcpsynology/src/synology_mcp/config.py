"""
Configuration loading for Synology MCP.

Priority order (highest → lowest):
  1. Environment variables  (SYNOLOGY_USER, SYNOLOGY_PASSWORD, SYNOLOGY_URL, …)
  2. macOS Keychain          (synology-mcp / synology-username, synology-password, synology-url)
  3. ~/.config/synology-mcp/config.yaml

Authentication:
  Session-based via SYNO.API.Auth (username + password).
  The client calls the login endpoint on startup to obtain a session SID,
  attaches _sid=<sid> to every request, and calls logout on shutdown.

  DSM API Auth v7 endpoint: GET /webapi/entry.cgi?api=SYNO.API.Auth&version=7
    &method=login&account=USER&passwd=PASS&format=sid

Never write secrets back to any file from this module.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml
import structlog

from synology_mcp.keychain import retrieve_secret

log = structlog.get_logger(__name__)

_CONFIG_FILE = Path.home() / ".config" / "synology-mcp" / "config.yaml"

_KEYCHAIN_USERNAME_ACCOUNT = "synology-username"
_KEYCHAIN_PASSWORD_ACCOUNT = "synology-password"
_KEYCHAIN_URL_ACCOUNT = "synology-url"


class Settings:
    """Runtime configuration resolved at startup."""

    def __init__(
        self,
        synology_url: str,
        username: str,
        password: str,
        ssl_verify: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self.synology_url = synology_url.rstrip("/")
        self.username = username
        self.password = password
        self.ssl_verify = ssl_verify
        self.timeout = timeout

    def __repr__(self) -> str:
        return (
            f"Settings(url={self.synology_url!r}, "
            f"username={self.username!r}, "
            f"ssl_verify={self.ssl_verify}, timeout={self.timeout})"
        )


def _load_yaml_config() -> dict:  # type: ignore[type-arg]
    """Load optional YAML config file, returning an empty dict if absent."""
    if _CONFIG_FILE.exists():
        with _CONFIG_FILE.open() as f:
            data = yaml.safe_load(f) or {}
        log.info("config.yaml_loaded", path=str(_CONFIG_FILE))
        return data  # type: ignore[return-value]
    return {}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Resolve and return the global Settings singleton.

    Raises ``RuntimeError`` if a required value cannot be found in any source.
    """
    yaml_cfg = _load_yaml_config()

    # --- Synology URL ---
    url: Optional[str] = (
        os.environ.get("SYNOLOGY_URL")
        or retrieve_secret(_KEYCHAIN_URL_ACCOUNT)
        or yaml_cfg.get("synology_url")
    )
    if not url:
        raise RuntimeError(
            "Synology URL not found. Set SYNOLOGY_URL env var, run "
            "scripts/setup_keychain.sh, or add 'synology_url' to "
            f"{_CONFIG_FILE}"
        )

    # --- Username ---
    username: Optional[str] = (
        os.environ.get("SYNOLOGY_USER")
        or retrieve_secret(_KEYCHAIN_USERNAME_ACCOUNT)
        or yaml_cfg.get("synology_username")
    )
    if not username:
        raise RuntimeError(
            "Synology username not found. Set SYNOLOGY_USER env var, run "
            "scripts/setup_keychain.sh, or add 'synology_username' to "
            f"{_CONFIG_FILE}"
        )

    # --- Password ---
    password: Optional[str] = (
        os.environ.get("SYNOLOGY_PASSWORD")
        or retrieve_secret(_KEYCHAIN_PASSWORD_ACCOUNT)
        or yaml_cfg.get("synology_password")
    )
    if not password:
        raise RuntimeError(
            "Synology password not found. Set SYNOLOGY_PASSWORD env var, run "
            "scripts/setup_keychain.sh, or add 'synology_password' to "
            f"{_CONFIG_FILE}"
        )

    # --- Optional settings ---
    ssl_verify_raw = (
        os.environ.get("SYNOLOGY_SSL_VERIFY")
        or str(yaml_cfg.get("ssl_verify", "true"))
    )
    ssl_verify = ssl_verify_raw.lower() not in ("false", "0", "no")

    timeout = float(
        os.environ.get("SYNOLOGY_TIMEOUT")
        or yaml_cfg.get("timeout", 30.0)
    )

    settings = Settings(
        synology_url=url,
        username=username,
        password=password,
        ssl_verify=ssl_verify,
        timeout=timeout,
    )
    log.info("config.resolved", settings=repr(settings))
    return settings
