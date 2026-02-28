"""
Configuration loading for Authentik MCP.

Priority order (highest → lowest):
  1. Environment variables (AUTHENTIK_TOKEN, AUTHENTIK_URL, AUTHENTIK_SSL_VERIFY)
  2. macOS Keychain  (authentik-mcp / authentik-token, authentik-url)
  3. ~/.config/authentik-mcp/config.yaml

Token is an Authentik API token (type "API", created in Admin → Directory → Tokens).
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
import structlog

from authentik_mcp.keychain import retrieve_secret

log = structlog.get_logger(__name__)

_CONFIG_FILE = Path.home() / ".config" / "authentik-mcp" / "config.yaml"
_KEYCHAIN_TOKEN_ACCOUNT = "authentik-token"
_KEYCHAIN_URL_ACCOUNT = "authentik-url"


class Settings:
    """Runtime configuration resolved at startup."""

    def __init__(
        self,
        authentik_url: str,
        api_token: str,
        ssl_verify: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self.authentik_url = authentik_url.rstrip("/")
        self.api_token = api_token
        self.ssl_verify = ssl_verify
        self.timeout = timeout

    def __repr__(self) -> str:
        return (
            f"Settings(url={self.authentik_url!r}, "
            f"ssl_verify={self.ssl_verify}, timeout={self.timeout})"
        )


def _load_yaml_config() -> dict:
    if _CONFIG_FILE.exists():
        with _CONFIG_FILE.open() as f:
            data = yaml.safe_load(f) or {}
        log.info("config.yaml_loaded", path=str(_CONFIG_FILE))
        return data
    return {}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Resolve and return the global Settings singleton."""
    yaml_cfg = _load_yaml_config()

    url = (
        os.environ.get("AUTHENTIK_URL")
        or retrieve_secret(_KEYCHAIN_URL_ACCOUNT)
        or yaml_cfg.get("authentik_url")
    )
    if not url:
        raise RuntimeError(
            "Authentik URL not found. Set AUTHENTIK_URL, store in Keychain, "
            "or add authentik_url to ~/.config/authentik-mcp/config.yaml"
        )

    token = (
        os.environ.get("AUTHENTIK_TOKEN")
        or retrieve_secret(_KEYCHAIN_TOKEN_ACCOUNT)
        or yaml_cfg.get("authentik_token")
    )
    if not token:
        raise RuntimeError(
            "Authentik API token not found. Set AUTHENTIK_TOKEN, store in Keychain, "
            "or add authentik_token to ~/.config/authentik-mcp/config.yaml"
        )

    ssl_verify = os.environ.get("AUTHENTIK_SSL_VERIFY", "true").lower() != "false"
    timeout = float(os.environ.get("AUTHENTIK_TIMEOUT", yaml_cfg.get("timeout", 30.0)))

    return Settings(authentik_url=url, api_token=token, ssl_verify=ssl_verify, timeout=timeout)
