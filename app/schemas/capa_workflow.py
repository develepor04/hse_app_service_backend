"""Request/response shapes for the WF-04 CAPA lifecycle.

Kept separate from schemas/capa_action.py, which is the website's plain CRUD
contract for the same table. Changing the lifecycle must not alter that shape.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Step 01 · raise ──────────────────────────────────────────────────────────
class CapaRaise(BaseModel):
    """Create an action against any event family.

    `subject_family` + `subject_id` are how a CAPA reaches audits, permits and
    the hazard register — the generic CRUD endpoint has no way to set them,
    which is why an audit finding could never raise one.
    """
    subject_family: str = Field(..., description="incident | near_miss | unsafe_act | risk | hazard_register | permit | audit")
    subject_id: int
    description: str = Field(..., min_length=5)
    root_cause_addressed: str = Field(..., min_length=3, description="Mandatory — the action cannot progress without it")
    action_type: str = Field("Corrective", description="Corrective | Preventive")
    source: Optional[str] = Field(None, description="incident | audit | risk_assessment | inspection | regulatory | proactive")
    responsible_person_id: Optional[int] = None
    due_date: Optional[date] = None
    capa_type: Optional[str] = Field(None, description="P1..P5 — otherwise inherited from the subject's priority")
    severity_potential: Optional[Any] = Field(None, description="low | medium | high, or 1-3")
    systemic_risk: Optional[Any] = Field(None, description="low | medium | high, or 1-3")


# ── Step 03 · plan ───────────────────────────────────────────────────────────
class CapaPlan(BaseModel):
    action_plan: str = Field(..., min_length=5)
    success_criteria: str = Field(..., min_length=5, description="What the evidence will be measured against at closure")
    action_category: str = Field(..., description="physical_fix | procedure_change | training | inspection | test | other")
    hierarchy_level: Optional[str] = Field(None, description="elimination | substitution | engineering | administrative | ppe")
    due_date: Optional[date] = None


class CapaPlanApproval(BaseModel):
    approved: bool = True
    notes: Optional[str] = None


# ── Step 05 · assign ─────────────────────────────────────────────────────────
class CapaAssign(BaseModel):
    responsible_person_id: int
    notes: Optional[str] = None


# ── Step 06 · do ─────────────────────────────────────────────────────────────
class CapaProgress(BaseModel):
    note: str = Field(..., min_length=3)
    percent_complete: Optional[int] = Field(None, ge=0, le=100)


class CapaInterimCheck(BaseModel):
    progress_is_real: bool = Field(..., description="Has the Supervisor seen actual progress")
    notes: Optional[str] = None


# ── Step 07 · evidence ───────────────────────────────────────────────────────
class CapaEvidenceCreate(BaseModel):
    evidence_type: str = Field(..., description="photo | document | training_record | test_report | inspection_confirmation")
    description: Optional[str] = None
    file_url: Optional[str] = Field(None, description="Path returned by the upload endpoint")
    # Required, not optional. CHECK 2 fails on any undated item and there is no
    # endpoint that can date one afterwards or remove it, so accepting an
    # undated attachment created an action that could never be closed and could
    # never be repaired either. The date is the whole point of the check: an
    # attachment that cannot be shown to post-date the action is exactly the
    # recycled evidence it exists to catch.
    evidence_date: datetime = Field(..., description="When the evidenced thing happened — not when it was uploaded")


class CapaEvidenceOut(BaseModel):
    id: int
    evidence_type: str
    file_url: Optional[str] = None
    description: Optional[str] = None
    evidence_date: Optional[datetime] = None
    uploaded_by: Optional[int] = None
    uploaded_at: Optional[datetime] = None
    validation_result: Optional[str] = None
    rejection_reason: Optional[str] = None

    model_config = {"from_attributes": True}


class CapaSubmit(BaseModel):
    """Owner marks the work done and hands it to validation."""
    notes: Optional[str] = None


# ── Step 08 · independent review ─────────────────────────────────────────────
class CapaIndependentReview(BaseModel):
    confirmed: bool = Field(..., description="Is the control physically in place as evidenced")
    notes: Optional[str] = None


# ── Step 10 · close ──────────────────────────────────────────────────────────
class CapaApproveClosure(BaseModel):
    approved: bool = True
    closure_notes: Optional[str] = None
    lesson_learned: Optional[str] = None
    # WF-04 measures effectiveness with the 30/60/90-day reviews, not with a
    # number typed at closure. This is kept because `capa_actions.effectiveness_rating`
    # is read by the incident trail and the exports, and the legacy sign-off
    # route was the only thing that ever wrote it — dropping it here would have
    # left that column empty for every action closed the correct way.
    effectiveness_rating: Optional[int] = Field(None, ge=1, le=5)


# ── Step 09 · effectiveness review ───────────────────────────────────────────
class CapaEffectivenessReviewSubmit(BaseModel):
    has_recurred: bool = Field(..., description="Has the same issue happened again")
    control_in_place: bool = Field(..., description="Is the control still physically there")
    root_cause_addressed: bool = Field(..., description="Was the underlying cause actually fixed")
    notes: Optional[str] = None


class CapaEffectivenessReviewOut(BaseModel):
    id: int
    capa_id: int
    review_point: int
    due_at: datetime
    result: str
    has_recurred: Optional[bool] = None
    control_in_place: Optional[bool] = None
    root_cause_addressed: Optional[bool] = None
    notes: Optional[str] = None
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    triggered_reopen: Optional[bool] = None

    model_config = {"from_attributes": True}


# ── Responses ────────────────────────────────────────────────────────────────
class ClosureCheckOut(BaseModel):
    key: str
    label: str
    passed: bool
    detail: str


class CapaDetail(BaseModel):
    id: int
    capa_ref: Optional[str] = None
    subject_family: Optional[str] = None
    subject_id: Optional[int] = None
    incident_id: Optional[int] = None
    source: Optional[str] = None

    description: Optional[str] = None
    root_cause_addressed: Optional[str] = None
    action_type: Optional[str] = None
    action_plan: Optional[str] = None
    success_criteria: Optional[str] = None
    action_category: Optional[str] = None
    hierarchy_level: Optional[str] = None

    responsible_person_id: Optional[int] = None
    responsible_person_name: Optional[str] = None
    due_date: Optional[date] = None
    status: Optional[str] = None

    # WF-04 priority
    severity_potential: Optional[int] = None
    systemic_risk: Optional[int] = None
    priority_score: Optional[int] = None
    priority_band: Optional[str] = None
    capa_type: Optional[str] = None
    capa_type_label: Optional[str] = None
    evidence_required: Optional[str] = None
    priority_explanation: Optional[str] = None

    # Lifecycle position
    step: Optional[int] = None
    step_label: Optional[str] = None
    total_steps: Optional[int] = None
    is_closed: Optional[bool] = None
    elapsed_percent: Optional[float] = None
    is_overdue: Optional[bool] = None
    escalation_level: Optional[int] = None
    reopened_count: Optional[int] = None
    systemic_flag: Optional[bool] = None
    is_locked: Optional[bool] = None

    plan_approved_at: Optional[datetime] = None
    interim_check_at: Optional[datetime] = None
    evidence_submitted_at: Optional[datetime] = None
    independent_review_at: Optional[datetime] = None
    independent_review_result: Optional[str] = None
    closed_at: Optional[datetime] = None
    lesson_learned: Optional[str] = None

    requires_plan_approval: Optional[bool] = None
    allowed_evidence_types: List[str] = Field(default_factory=list)
    closure_checks: List[ClosureCheckOut] = Field(default_factory=list)
    evidence: List[CapaEvidenceOut] = Field(default_factory=list)
    effectiveness_reviews: List[CapaEffectivenessReviewOut] = Field(default_factory=list)
    next_action: Optional[str] = None
