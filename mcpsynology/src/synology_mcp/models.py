"""
Pydantic models for Synology DSM API inputs.

All tool input models use strict validation to prevent injection or
unexpected data reaching the DSM API.
"""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

# Shared folder names: letters, digits, hyphens, underscores, spaces, dots
_SAFE_SHARE_RE = re.compile(r"^[\w\-. ]{1,64}$")

# File paths: alphanumeric, slashes, hyphens, underscores, dots, spaces
_SAFE_PATH_RE = re.compile(r"^[/\w\-. ]{1,512}$")


def _require_safe_share(v: str) -> str:
    if not _SAFE_SHARE_RE.match(v):
        raise ValueError("share name contains illegal characters or is too long")
    return v


def _require_safe_path(v: str) -> str:
    if not _SAFE_PATH_RE.match(v):
        raise ValueError("path contains illegal characters or is too long")
    if ".." in v:
        raise ValueError("path traversal ('..') is not allowed")
    return v


# ---------------------------------------------------------------------------
# MCP tool input schemas
# ---------------------------------------------------------------------------


class ShareInput(BaseModel):
    """Input for operations that target a specific shared folder."""

    share_name: str = Field(
        ...,
        description="Shared folder name (e.g. 'docker', 'homes')",
        min_length=1,
        max_length=64,
    )

    @field_validator("share_name")
    @classmethod
    def sanitize_share(cls, v: str) -> str:
        return _require_safe_share(v)


class ListFilesInput(BaseModel):
    """Input for FileStation directory listing."""

    folder_path: str = Field(
        ...,
        description="Absolute path to a shared folder or subfolder (e.g. '/docker', '/homes/admin')",
        min_length=1,
        max_length=512,
    )
    additional: Optional[str] = Field(
        default=None,
        description="Comma-separated extra fields to return: real_path, size, owner, time, perm, type",
    )

    @field_validator("folder_path")
    @classmethod
    def sanitize_path(cls, v: str) -> str:
        return _require_safe_path(v)


class PackageInput(BaseModel):
    """Input for package operations."""

    package_id: str = Field(
        ...,
        description="Package ID as shown in the Package Center (e.g. 'ContainerManager', 'HyperBackup')",
        min_length=1,
        max_length=128,
    )

    @field_validator("package_id")
    @classmethod
    def sanitize_id(cls, v: str) -> str:
        if not re.match(r"^[\w\-]{1,128}$", v):
            raise ValueError("package_id contains illegal characters")
        return v
