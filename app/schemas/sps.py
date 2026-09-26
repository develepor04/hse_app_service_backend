"""Schemas for WF-07 · Safety Performance Scoring."""
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class SpsDomainBreakdown(BaseModel):
    hazard_exposure: float
    control_integrity: float
    work_discipline: float
    human_readiness: float
    org_health: float


class SpsScoreResponse(BaseModel):
    """Weekly 0-100, five domain breakdown. Higher is worse."""

    scope: str
    site_id: Optional[int] = None
    employee_id: Optional[int] = None
    period_start: date
    period_end: date
    sps: float
    band: str
    domains: SpsDomainBreakdown
    weights: Dict[str, float]
    stale_data_penalty: float
    data_completeness: float
    explanation: str
    inputs: Optional[Dict[str, Any]] = None
    previous_sps: Optional[float] = None
    delta: Optional[float] = None


class SpsSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scope: str
    site_id: Optional[int] = None
    employee_id: Optional[int] = None
    period_start: date
    period_end: date
    hazard_exposure: float
    control_integrity: float
    work_discipline: float
    human_readiness: float
    org_health: float
    sps: float
    band: str
    data_completeness: Optional[float] = None
    stale_data_penalty: float
    computed_at: Optional[datetime] = None


class SpsAlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sps_snapshot_id: Optional[int] = None
    site_id: Optional[int] = None
    alert_type: str
    delta: Optional[float] = None
    previous_band: Optional[str] = None
    new_band: Optional[str] = None
    severity: Optional[str] = None
    message: Optional[str] = None
    suggested_capa: Optional[List[Dict[str, Any]]] = None
    acknowledged_by: Optional[int] = None
    acknowledged_at: Optional[datetime] = None
    capa_action_id: Optional[int] = None


class SpsAlertAck(BaseModel):
    create_capa: bool = False
    capa_description: Optional[str] = None
    capa_owner_employee_id: Optional[int] = None
    due_days: int = 14


class MySafetyScoreResponse(BaseModel):
    """The worker's personal Human Readiness contribution — competence gaps and
    fatigue flags only. A worker never sees another person's score."""

    employee_id: int
    human_readiness: float
    band: str
    open_competence_gaps: int
    safety_critical_gaps: int
    latest_fatigue_index: Optional[float] = None
    latest_fatigue_band: Optional[str] = None
    blocked_tasks: List[str] = []
    guidance: str


class DataQualityRow(BaseModel):
    """Auditor's Data Integrity & Validation screen."""

    source_table: str
    last_verified_at: Optional[datetime] = None
    days_stale: Optional[int] = None
    is_data_gap: bool
    record_count: int


class DataQualityResponse(BaseModel):
    stale_threshold_days: int
    stale_sources: int
    penalty_applied: float
    confidence_score: float
    rows: List[DataQualityRow]
