"""
Pydantic models for Proxmox VE API responses and MCP tool inputs.

All tool input models use strict validation to prevent injection or
unexpected data reaching the Proxmox API.
"""
from __future__ import annotations

import re
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------

_SAFE_NODE_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")
_SAFE_VMID_RE = re.compile(r"^\d{1,7}$")


def _require_safe_node(v: str) -> str:
    if not _SAFE_NODE_RE.match(v):
        raise ValueError("node name contains illegal characters or is too long")
    return v


def _require_safe_vmid(v: int) -> int:
    if v < 100 or v > 9_999_999:
        raise ValueError("vmid must be between 100 and 9999999")
    return v


# ---------------------------------------------------------------------------
# MCP tool input schemas
# ---------------------------------------------------------------------------


class NodeInput(BaseModel):
    """Input requiring a node name."""
    node: str = Field(..., description="Proxmox node name", min_length=1, max_length=64)

    @field_validator("node")
    @classmethod
    def sanitize_node(cls, v: str) -> str:
        return _require_safe_node(v)


class VmInput(BaseModel):
    """Input for a QEMU VM or LXC operation on a specific node."""
    node: str = Field(..., description="Proxmox node name", min_length=1, max_length=64)
    vmid: int = Field(..., description="VM or container ID (100–9999999)", ge=100, le=9_999_999)

    @field_validator("node")
    @classmethod
    def sanitize_node(cls, v: str) -> str:
        return _require_safe_node(v)


class StorageInput(BaseModel):
    """Input for storage operations."""
    node: str = Field(..., description="Proxmox node name", min_length=1, max_length=64)
    storage: str = Field(..., description="Storage ID", min_length=1, max_length=64)

    @field_validator("node", "storage")
    @classmethod
    def sanitize_names(cls, v: str) -> str:
        if not _SAFE_NODE_RE.match(v):
            raise ValueError(f"'{v}' contains illegal characters")
        return v


class ShutdownVmInput(BaseModel):
    """Input for graceful VM/LXC shutdown with optional timeout."""
    node: str = Field(..., description="Proxmox node name", min_length=1, max_length=64)
    vmid: int = Field(..., description="VM or container ID", ge=100, le=9_999_999)
    timeout: Optional[int] = Field(
        default=60,
        description="Seconds to wait for graceful shutdown before forcing (default 60)",
        ge=1,
        le=600,
    )

    @field_validator("node")
    @classmethod
    def sanitize_node(cls, v: str) -> str:
        return _require_safe_node(v)
