from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class NoonReport(BaseModel):
    vessel_name: str
    imo: str
    report_date: date
    lat: float
    lon: float
    speed_kn: float
    me_consumption_mt: float
    ae_consumption_mt: float
    rob_hfo_mt: float
    rob_mgo_mt: float
    distance_nm: float


class PortCall(BaseModel):
    imo: str
    port_name: str
    planned_eta: datetime
    actual_eta: datetime | None = None
    berth_window_end: datetime


class BunkerEntry(BaseModel):
    imo: str
    log_date: date
    hfo_consumed_mt: float
    mgo_consumed_mt: float
    speed_kn: float


class MaintenanceItem(BaseModel):
    imo: str
    equipment: str
    description: str
    due_date: date
    status: Literal["open", "closed", "in_progress"]
    severity: Literal["low", "medium", "high", "critical"]


class VesselSnapshot(BaseModel):
    imo: str
    vessel_name: str
    noon: NoonReport | None = None
    port_calls: list[PortCall] = Field(default_factory=list)
    bunker_entries: list[BunkerEntry] = Field(default_factory=list)
    maintenance: list[MaintenanceItem] = Field(default_factory=list)


class Anomaly(BaseModel):
    vessel_imo: str
    vessel_name: str
    type: Literal["fuel", "schedule", "maintenance"]
    severity: Literal["low", "medium", "high", "critical"]
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class Escalation(BaseModel):
    vessel_imo: str
    vessel_name: str
    title: str
    severity: Literal["high", "critical"]
    owner: str
    deadline: date
    rationale: str
    evidence_refs: list[str] = Field(default_factory=list)


class FleetHealthReport(BaseModel):
    report_id: str
    generated_at: datetime
    fleet_summary: str
    vessel_summaries: list[dict[str, Any]]
    anomalies: list[Anomaly]
    escalations: list[Escalation]
    markdown: str
    memory_notes: list[str] = Field(default_factory=list)
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)


class PipelineState(BaseModel):
    """Shared state passed through LangGraph nodes."""

    skip_llm: bool = False
    vessel_imos: list[str] = Field(default_factory=list)
    input_paths: dict[str, str] = Field(default_factory=dict)
    snapshots: list[VesselSnapshot] = Field(default_factory=list)
    anomalies: list[Anomaly] = Field(default_factory=list)
    escalations: list[Escalation] = Field(default_factory=list)
    fleet_summary: str = ""
    vessel_summaries: list[dict[str, Any]] = Field(default_factory=list)
    markdown: str = ""
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    memory_notes: list[str] = Field(default_factory=list)
    report_id: str = ""
