"""
Configuration loading for Grafana MCP.

Priority order (highest → lowest):
  1. Environment variables (GRAFANA_TOKEN, GRAFANA_URL, GRAFANA_SSL_VERIFY)
  2. macOS Keychain  (grafana-mcp / grafana-token, grafana-url)
  3. ~/.config/grafana-mcp/config.yaml

Token is a Grafana service-account token (Bearer token).
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
import structlog

from grafana_mcp.keychain import retrieve_secret

log = structlog.get_logger(__name__)

_CONFIG_FILE = Path.home() / ".config" / "grafana-mcp" / "config.yaml"
_KEYCHAIN_TOKEN_ACCOUNT = "grafana-token"
_KEYCHAIN_URL_ACCOUNT = "grafana-url"


class Settings:
    """Runtime configuration resolved at startup."""

    def __init__(
        self,
        grafana_url: str,
        api_token: str,
        ssl_verify: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self.grafana_url = grafana_url.rstrip("/")
        self.api_token = api_token
        self.ssl_verify = ssl_verify
        self.timeout = timeout

    def __repr__(self) -> str:
        return (
            f"Settings(url={self.grafana_url!r}, "
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
        os.environ.get("GRAFANA_URL")
        or retrieve_secret(_KEYCHAIN_URL_ACCOUNT)
        or yaml_cfg.get("grafana_url")
    )
    if not url:
        raise RuntimeError(
            "Grafana URL not found. Set GRAFANA_URL, store in Keychain, "
            "or add grafana_url to ~/.config/grafana-mcp/config.yaml"
        )

    token = (
        os.environ.get("GRAFANA_TOKEN")
        or retrieve_secret(_KEYCHAIN_TOKEN_ACCOUNT)
        or yaml_cfg.get("grafana_token")
    )
    if not token:
        raise RuntimeError(
            "Grafana API token not found. Set GRAFANA_TOKEN, store in Keychain, "
            "or add grafana_token to ~/.config/grafana-mcp/config.yaml"
        )

    ssl_verify = os.environ.get("GRAFANA_SSL_VERIFY", "true").lower() != "false"
    timeout = float(os.environ.get("GRAFANA_TIMEOUT", yaml_cfg.get("timeout", 30.0)))

    return Settings(grafana_url=url, api_token=token, ssl_verify=ssl_verify, timeout=timeout)
