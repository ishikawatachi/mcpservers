"""
Configuration loading for Synology MCP.

Priority order (highest → lowest):
  1. Environment variables  (SYNOLOGY_TOKEN, SYNOLOGY_URL, …)
  2. macOS Keychain          (synology-mcp / synology-token, synology-url)
  3. ~/.config/synology-mcp/config.yaml

Authentication:
  - DSM 7.2.2+ → Personal Access Token (PAT)
      Create in DSM: Control Panel → Personal → Security → Account →
                     Personal Access Tokens → Add
      The PAT is sent as:
        • Authorization: Bearer <token>   (WebAPI v7+ endpoints)
        • _sid=<token> query parameter    (older CGI endpoints like Storage.CGI)

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

_KEYCHAIN_TOKEN_ACCOUNT = "synology-token"
_KEYCHAIN_URL_ACCOUNT = "synology-url"


class Settings:
    """Runtime configuration resolved at startup."""

    def __init__(
        self,
        synology_url: str,
        api_token: str,
        ssl_verify: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self.synology_url = synology_url.rstrip("/")
        self.api_token = api_token          # Personal Access Token
        self.ssl_verify = ssl_verify
        self.timeout = timeout

    def __repr__(self) -> str:
        return (
            f"Settings(url={self.synology_url!r}, "
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

    # --- Personal Access Token ---
    token: Optional[str] = (
        os.environ.get("SYNOLOGY_TOKEN")
        or retrieve_secret(_KEYCHAIN_TOKEN_ACCOUNT)
        or yaml_cfg.get("synology_token")
    )
    if not token:
        raise RuntimeError(
            "Synology PAT not found. Set SYNOLOGY_TOKEN env var, run "
            "scripts/setup_keychain.sh, or add 'synology_token' to "
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
        api_token=token,
        ssl_verify=ssl_verify,
        timeout=timeout,
    )
    log.info("config.resolved", settings=repr(settings))
    return settings
