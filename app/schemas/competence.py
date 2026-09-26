"""Schemas for WF-06 · Training, Competence & Human Readiness."""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Master data ───────────────────────────────────────────────────────────────
class CertificationTypeCreate(BaseModel):
    name: str = Field(..., min_length=1)
    code: Optional[str] = None
    issuing_body: Optional[str] = None
    validity_months: Optional[int] = None
    is_safety_critical: bool = False
    description: Optional[str] = None


class CertificationTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organisation_id: Optional[int] = None
    name: str
    code: Optional[str] = None
    issuing_body: Optional[str] = None
    validity_months: Optional[int] = None
    is_safety_critical: int = 0
    description: Optional[str] = None


class CompetenceMatrixCreate(BaseModel):
    requirement_name: str = Field(..., min_length=1)
    competence_profile_id: Optional[int] = None
    role_id: Optional[int] = None
    training_program_id: Optional[int] = None
    certification_type_id: Optional[int] = None
    is_mandatory: bool = True
    is_safety_critical: bool = False
    validity_months: Optional[int] = None
    permit_types_gated: Optional[List[int]] = None


class CompetenceMatrixResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organisation_id: Optional[int] = None
    requirement_name: str
    competence_profile_id: Optional[int] = None
    role_id: Optional[int] = None
    training_program_id: Optional[int] = None
    certification_type_id: Optional[int] = None
    is_mandatory: int = 1
    is_safety_critical: int = 0
    validity_months: Optional[int] = None
    permit_types_gated: Optional[List[int]] = None


# ── Training records ──────────────────────────────────────────────────────────
class TrainingRecordCreate(BaseModel):
    employee_id: Optional[int] = None  # defaults to the caller
    training_program_id: Optional[int] = None
    certification_type_id: Optional[int] = None
    competence_matrix_id: Optional[int] = None
    course_name: Optional[str] = None
    completed_at: Optional[date] = None
    expires_at: Optional[date] = None
    score: Optional[float] = None
    result: Optional[str] = None  # pass | fail | pending
    certificate_ref: Optional[str] = None
    evidence_photo: Optional[str] = None


class TrainingRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    course_name: Optional[str] = None
    training_program_id: Optional[int] = None
    certification_type_id: Optional[int] = None
    completed_at: Optional[date] = None
    expires_at: Optional[date] = None
    score: Optional[float] = None
    result: Optional[str] = None
    certificate_ref: Optional[str] = None
    verified_by: Optional[int] = None
    verified_at: Optional[datetime] = None
    toolbox_acknowledged_at: Optional[datetime] = None


class TrainingVerify(BaseModel):
    """Auditor/supervisor verifies a certificate against the matrix."""

    verified: bool = True
    notes: Optional[str] = None


# ── Competence card / gaps ────────────────────────────────────────────────────
class CompetenceCardItem(BaseModel):
    requirement_name: str
    competence_matrix_id: Optional[int] = None
    is_safety_critical: bool = False
    status: str  # valid | expiring | expired | missing
    expires_at: Optional[date] = None
    days_to_expiry: Optional[int] = None
    blocks_permit: bool = False


class CompetenceCardResponse(BaseModel):
    """The worker's competence card — 60/30/7 expiry, and what is blocked."""

    employee_id: int
    employee_name: Optional[str] = None
    items: List[CompetenceCardItem]
    valid_count: int
    expiring_count: int
    expired_count: int
    missing_count: int
    blocked_tasks: List[str]
    is_new_worker: bool = False


class CompetenceGapResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    requirement_name: Optional[str] = None
    gap_type: str
    is_safety_critical: int = 0
    expires_at: Optional[date] = None
    detected_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    buddy_employee_id: Optional[int] = None


class TeamMatrixRow(BaseModel):
    employee_id: int
    employee_name: Optional[str] = None
    valid_count: int
    expiring_count: int
    expired_count: int
    missing_count: int
    is_blocked: bool
    buddy_required: bool = False


class BuddyAssign(BaseModel):
    employee_id: int
    buddy_employee_id: int
    competence_gap_id: Optional[int] = None


class TrainingEffectivenessResponse(BaseModel):
    """Monthly training effectiveness — incident rate trained vs untrained."""

    period_months: int
    trained_employees: int
    untrained_employees: int
    incidents_trained: int
    incidents_untrained: int
    rate_trained: float
    rate_untrained: float
    effectiveness_ratio: Optional[float] = None
    interpretation: str


# ── Fatigue ───────────────────────────────────────────────────────────────────
class FatigueDeclare(BaseModel):
    shift_hours: float = Field(..., ge=0, le=24)
    consecutive_days: int = Field(0, ge=0, le=60)
    night_shifts_7d: int = Field(0, ge=0, le=7)
    task_intensity: Optional[str] = None
    employee_id: Optional[int] = None  # supervisors may declare on behalf


class FatigueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    declared_at: Optional[datetime] = None
    shift_hours: float
    consecutive_days: int
    night_shifts_7d: int
    task_intensity: Optional[str] = None
    fatigue_index: float
    band: str
    supervisor_ack_at: Optional[datetime] = None
    supervisor_signoff_at: Optional[datetime] = None
    exception_at: Optional[datetime] = None
    exception_reason: Optional[str] = None


class FatigueIndexResponse(BaseModel):
    """Live index without persisting — what the worker sees before requesting."""

    fatigue_index: float
    band: str
    shift_component: float
    consecutive_component: float
    night_component: float
    requires_supervisor_ack: bool
    requires_signoff: bool
    is_hard_block: bool
    explanation: str


class FatigueAck(BaseModel):
    note: Optional[str] = None


class FatigueException(BaseModel):
    """Safety Manager only — the sole way past a >=20 hard block."""

    reason: str = Field(..., min_length=10)
