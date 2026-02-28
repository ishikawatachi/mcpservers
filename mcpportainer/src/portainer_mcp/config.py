"""
Configuration loading for Portainer MCP.

Priority order (highest → lowest):
  1. Environment variables (PORTAINER_TOKEN, PORTAINER_URL, …)
  2. macOS Keychain (portainer-mcp / portainer-token, portainer-url)
  3. ~/.config/portainer-mcp/config.yaml

Never write secrets back to any file from this module.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml
import structlog

from portainer_mcp.keychain import retrieve_secret

log = structlog.get_logger(__name__)

_CONFIG_FILE = Path.home() / ".config" / "portainer-mcp" / "config.yaml"

_KEYCHAIN_TOKEN_ACCOUNT = "portainer-token"
_KEYCHAIN_URL_ACCOUNT = "portainer-url"


class Settings:
    """Runtime configuration resolved at startup."""

    def __init__(
        self,
        portainer_url: str,
        api_token: str,
        ssl_verify: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self.portainer_url = portainer_url.rstrip("/")
        self.api_token = api_token
        self.ssl_verify = ssl_verify
        self.timeout = timeout

    def __repr__(self) -> str:
        return (
            f"Settings(url={self.portainer_url!r}, "
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

    # --- Portainer URL ---
    url = (
        os.environ.get("PORTAINER_URL")
        or retrieve_secret(_KEYCHAIN_URL_ACCOUNT)
        or yaml_cfg.get("portainer_url")
    )
    if not url:
        raise RuntimeError(
            "Portainer URL not found. Set PORTAINER_URL env var, store it in Keychain "
            "(account 'portainer-url'), or add 'portainer_url' to "
            f"{_CONFIG_FILE}."
        )

    # --- API Token ---
    token = (
        os.environ.get("PORTAINER_TOKEN")
        or retrieve_secret(_KEYCHAIN_TOKEN_ACCOUNT)
        or yaml_cfg.get("api_token")
    )
    if not token:
        raise RuntimeError(
            "Portainer API token not found. Set PORTAINER_TOKEN env var, store it in "
            "Keychain (account 'portainer-token'), or add 'api_token' to "
            f"{_CONFIG_FILE}."
        )

    ssl_verify = bool(
        os.environ.get("PORTAINER_SSL_VERIFY", yaml_cfg.get("ssl_verify", True))
    )
    timeout = float(
        os.environ.get("PORTAINER_TIMEOUT", yaml_cfg.get("timeout", 30.0))
    )

    settings = Settings(
        portainer_url=url,
        api_token=token,
        ssl_verify=ssl_verify,
        timeout=timeout,
    )
    log.info("config.resolved", settings=repr(settings))
    return settings
