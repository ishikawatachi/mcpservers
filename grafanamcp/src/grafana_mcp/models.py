"""Pydantic response models for the Grafana API."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class Dashboard(BaseModel):
    uid: str
    title: str
    url: str
    folderTitle: Optional[str] = None
    tags: list[str] = []


class DashboardSummary(BaseModel):
    uid: str
    title: str
    tags: list[str] = []
    folder_uid: Optional[str] = None
    folder_title: Optional[str] = None
    panel_count: int = 0
    panel_types: list[str] = []
    variable_count: int = 0
    time_from: Optional[str] = None
    time_to: Optional[str] = None


class PanelQuery(BaseModel):
    panel_id: int
    panel_title: str
    panel_type: str
    datasource_uid: Optional[str] = None
    datasource_type: Optional[str] = None
    targets: list[dict[str, Any]] = []


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
    folderUID: Optional[str] = None
    ruleGroup: Optional[str] = None
    condition: Optional[str] = None
    data: list[Any] = []
    noDataState: str = "NoData"
    execErrState: str = "Error"


class ContactPoint(BaseModel):
    uid: Optional[str] = None
    name: str
    type: str
    settings: dict[str, Any] = {}


class NotificationPolicy(BaseModel):
    receiver: str
    group_by: list[str] = []
    routes: list[Any] = []


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


class Team(BaseModel):
    id: int
    orgId: int
    name: str
    email: Optional[str] = None
    memberCount: int = 0


class Organization(BaseModel):
    id: int
    name: str


class Annotation(BaseModel):
    id: int
    dashboardUID: Optional[str] = None
    panelId: Optional[int] = None
    time: int
    timeEnd: Optional[int] = None
    text: str
    tags: list[str] = []
