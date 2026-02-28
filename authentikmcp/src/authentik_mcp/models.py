"""Pydantic response models for the Authentik API (stubs — expand as tools are built)."""
from __future__ import annotations

from pydantic import BaseModel
from typing import Optional


class AuthentikUser(BaseModel):
    pk: int
    username: str
    name: str
    email: Optional[str] = None
    is_active: bool = True
    is_superuser: bool = False


class Group(BaseModel):
    pk: str
    name: str
    is_superuser: bool = False
    parent: Optional[str] = None


class Application(BaseModel):
    pk: str
    name: str
    slug: str
    provider: Optional[int] = None
    meta_launch_url: Optional[str] = None


class Flow(BaseModel):
    pk: str
    name: str
    slug: str
    designation: str  # e.g. "authentication", "enrollment", "recovery"


class Token(BaseModel):
    pk: str
    identifier: str
    intent: str  # e.g. "api", "verification"
    user: Optional[str] = None
    expiring: bool = True
