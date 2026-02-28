"""
Configuration loading for Proxmox MCP.

Priority order (highest → lowest):
  1. Environment variables (PROXMOX_TOKEN, PROXMOX_URL, …)
  2. macOS Keychain (proxmox-mcp / proxmox-token, proxmox-url)
  3. ~/.config/proxmox-mcp/config.yaml

The API token must be the full Proxmox token identifier including user, realm,
and token ID in the format:  user@realm!tokenid=uuid
  Example:                   root@pam!mcp=dfba4d3d-4005-4c42-95be-bb1cc805c857

Never write secrets back to any file from this module.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml
import structlog

from proxmox_mcp.keychain import retrieve_secret

log = structlog.get_logger(__name__)

_CONFIG_FILE = Path.home() / ".config" / "proxmox-mcp" / "config.yaml"

_KEYCHAIN_TOKEN_ACCOUNT = "proxmox-token"
_KEYCHAIN_URL_ACCOUNT = "proxmox-url"


class Settings:
    """Runtime configuration resolved at startup."""

    def __init__(
        self,
        proxmox_url: str,
        api_token: str,
        ssl_verify: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self.proxmox_url = proxmox_url.rstrip("/")
        self.api_token = api_token  # full string: user@realm!tokenid=uuid
        self.ssl_verify = ssl_verify
        self.timeout = timeout

    def __repr__(self) -> str:
        return (
            f"Settings(url={self.proxmox_url!r}, "
            f"ssl_verify={self.ssl_verify}, timeout={self.timeout})"
        )


def _load_yaml_config() -> dict:
    """Load optional YAML config file, returning an empty dict if absent."""
    if _CONFIG_FILE.exists():
        with _CONFIG_FILE.open() as f:
            data = yaml.safe_load(f) or {}
        log.info("config.yaml_loaded", path=str(_CONFIG_FILE))
        return data
    return {}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Resolve and return the global Settings singleton.

    Raises ``RuntimeError`` if a required value cannot be found in any source.
    """
    yaml_cfg = _load_yaml_config()

    # --- Proxmox URL ---
    url = (
        os.environ.get("PROXMOX_URL")
        or retrieve_secret(_KEYCHAIN_URL_ACCOUNT)
        or yaml_cfg.get("proxmox_url")
    )
    if not url:
        raise RuntimeError(
            "Proxmox URL not found. Set PROXMOX_URL env var, store it in Keychain "
            "(account 'proxmox-url'), or add 'proxmox_url' to "
            f"{_CONFIG_FILE}"
        )

    # --- API Token ---
    token = (
        os.environ.get("PROXMOX_TOKEN")
        or retrieve_secret(_KEYCHAIN_TOKEN_ACCOUNT)
        or yaml_cfg.get("proxmox_token")
    )
    if not token:
        raise RuntimeError(
            "Proxmox API token not found. Set PROXMOX_TOKEN env var, store it in Keychain "
            "(account 'proxmox-token'), or add 'proxmox_token' to "
            f"{_CONFIG_FILE}. "
            "Token format: user@realm!tokenid=uuid  (e.g. root@pam!mcp=<uuid>)"
        )

    # --- SSL verification ---
    ssl_verify_raw = (
        os.environ.get("PROXMOX_SSL_VERIFY")
        or str(yaml_cfg.get("ssl_verify", "true"))
    )
    ssl_verify = ssl_verify_raw.lower() not in ("false", "0", "no")

    # --- Timeout ---
    timeout = float(
        os.environ.get("PROXMOX_TIMEOUT")
        or yaml_cfg.get("timeout", 30.0)
    )

    settings = Settings(
        proxmox_url=url,
        api_token=token,
        ssl_verify=ssl_verify,
        timeout=timeout,
    )
    log.info("config.resolved", settings=repr(settings))
    return settings
