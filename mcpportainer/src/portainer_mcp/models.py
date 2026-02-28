"""
Pydantic models for Portainer API responses and MCP tool inputs.

All models use strict validation to prevent injection or unexpected data.
"""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Portainer API response models
# ---------------------------------------------------------------------------


class ContainerPort(BaseModel):
    IP: Optional[str] = None
    PrivatePort: Optional[int] = None
    PublicPort: Optional[int] = None
    Type: Optional[str] = None


class ContainerSummary(BaseModel):
    Id: str
    Names: list[str] = []
    Image: str = ""
    ImageID: str = ""
    Command: str = ""
    Created: int = 0
    State: str = ""
    Status: str = ""
    Ports: list[ContainerPort] = []
    Labels: dict[str, str] = {}


class ContainerDetail(BaseModel):
    Id: str
    Name: str = ""
    Image: str = ""
    State: dict[str, Any] = {}
    Config: dict[str, Any] = {}
    HostConfig: dict[str, Any] = {}
    NetworkSettings: dict[str, Any] = {}
    Mounts: list[dict[str, Any]] = []


class ImageSummary(BaseModel):
    Id: str
    RepoTags: list[str] = []
    RepoDigests: list[str] = []
    Size: int = 0
    Created: int = 0
    Labels: dict[str, str] = {}


class Stack(BaseModel):
    Id: int
    Name: str
    Type: int = 1  # 1=swarm, 2=compose
    EndpointId: int = 0
    Status: int = 1  # 1=active, 2=inactive
    CreationDate: int = 0
    UpdateDate: int = 0


class Endpoint(BaseModel):
    Id: int
    Name: str
    URL: str = ""
    Type: int = 1
    Status: int = 1


# ---------------------------------------------------------------------------
# MCP tool input schemas
# ---------------------------------------------------------------------------


class EndpointIdInput(BaseModel):
    """Require an integer endpoint ID."""
    endpoint_id: int = Field(..., description="Portainer endpoint (environment) ID", ge=1)


class ContainerInput(BaseModel):
    """Container operation input."""
    endpoint_id: int = Field(..., description="Portainer endpoint ID", ge=1)
    container_id: str = Field(..., description="Container ID or name", min_length=1, max_length=128)

    @field_validator("container_id")
    @classmethod
    def sanitize_container_id(cls, v: str) -> str:
        """Reject shell metacharacters."""
        forbidden = set(";&|`$><\\\"'()")
        if any(c in forbidden for c in v):
            raise ValueError("container_id contains illegal characters")
        return v


class ContainerLogsInput(BaseModel):
    """Input for container log retrieval."""
    endpoint_id: int = Field(..., description="Portainer endpoint ID", ge=1)
    container_id: str = Field(..., description="Container ID or name", min_length=1, max_length=128)
    tail: int = Field(100, description="Number of log lines to return", ge=1, le=5000)
    timestamps: bool = Field(False, description="Include timestamps in log output")

    @field_validator("container_id")
    @classmethod
    def sanitize_container_id(cls, v: str) -> str:
        forbidden = set(";&|`$><\\\"'()")
        if any(c in forbidden for c in v):
            raise ValueError("container_id contains illegal characters")
        return v


class DeployStackInput(BaseModel):
    """Input for deploying or updating a Docker Compose stack."""
    endpoint_id: int = Field(..., description="Portainer endpoint ID", ge=1)
    stack_name: str = Field(..., description="Stack name", min_length=1, max_length=64)
    compose_content: str = Field(..., description="Docker Compose YAML content", min_length=1)
    env_vars: dict[str, str] = Field(default_factory=dict, description="Environment variables for the stack")

    @field_validator("stack_name")
    @classmethod
    def sanitize_stack_name(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("stack_name must contain only alphanumerics, hyphens, and underscores")
        return v
