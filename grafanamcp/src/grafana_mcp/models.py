"""Pydantic response models for the Grafana API (stubs — expand as tools are built)."""
from __future__ import annotations

from pydantic import BaseModel
from typing import Optional


class Dashboard(BaseModel):
    uid: str
    title: str
    url: str
    folderTitle: Optional[str] = None
    tags: list[str] = []


class Datasource(BaseModel):
    id: int
    uid: str
    name: str
    type: str
    url: Optional[str] = None
    access: str = "proxy"


class AlertRule(BaseModel):
    uid: str
    title: str
    state: str  # e.g. "OK", "Alerting", "NoData"


class Folder(BaseModel):
    id: int
    uid: str
    title: str


class GrafanaUser(BaseModel):
    id: int
    login: str
    email: str
    name: Optional[str] = None
    isAdmin: bool = False
