"""Request/response schemas for the Hazard register workflow (flow 5).

The register runs the same eight stages as every other safety event
(HSE_Workflow_Engine_Slide.pptx). One schema per stage verb, so a request body
cannot carry a field belonging to a stage the hazard is not in:

    02 ASSESS   HazardAssess          open → interim_control | under_review
    03 RESPOND  HazardInterimControl  → interim_control
    04 INVESTIGATE HazardStartReview  → under_review
    05 IMPROVE  HazardPlanControls    → controls_planned
                HazardSubmitVerification → pending_verification
    06 VERIFY   HazardVerifyControls  → controlled | back to controls_planned
    07 LEARN    HazardLesson          records the lesson, stays at controlled
    08 CLOSE    HazardClose           → closed

Separate from schemas/hazard.py (the website's catalog CRUD) so the register
workflow cannot alter the catalog contract.
"""
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════════════════════════
# 01 RECORD
# ══════════════════════════════════════════════════════════════════════════════
class HazardLog(BaseModel):
    """Worker/supervisor logs a field hazard into the register."""

    hazard_name: str = Field(..., min_length=1)
    category_id: Optional[int] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    probability: Optional[str] = None
    location: Optional[str] = None
    location_station_id: Optional[int] = None
    still_present: Optional[bool] = None
    controls: Optional[str] = None
    persons_exposed: Optional[int] = Field(
        None, ge=0, description="How many people the hazard can reach"
    )
    gps_latitude: Optional[str] = None
    gps_longitude: Optional[str] = None
    # Uploaded files arrive as multipart and are folded in here by
    # report_media.merge_media, under the name every other form already uses.
    photos: Optional[List[str]] = None


# ══════════════════════════════════════════════════════════════════════════════
# 02 ASSESS
# ══════════════════════════════════════════════════════════════════════════════
class HazardAssess(BaseModel):
    """Triage the logged hazard.

    Severity and probability may be corrected here: what the reporter felt in
    the field and what the assessor scores are routinely different, and the
    score that ranks the hazard has to be the assessor's.
    """

    severity: Optional[str] = None
    probability: Optional[str] = None
    persons_exposed: Optional[int] = Field(None, ge=0)
    work_stopped: bool = Field(
        False, description="The hazard was severe enough to stop the job"
    )
    assessment_notes: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# 03 RESPOND
# ══════════════════════════════════════════════════════════════════════════════
class HazardInterimControl(BaseModel):
    """The temporary measure holding the hazard while the fix is designed."""

    interim_control: str = Field(
        ..., min_length=1, description="What was put in place right now"
    )
    work_stopped: Optional[bool] = None


# ══════════════════════════════════════════════════════════════════════════════
# 04 INVESTIGATE
# ══════════════════════════════════════════════════════════════════════════════
class HazardStartReview(BaseModel):
    """Open the control review. Body optional — the act is the state change."""

    review_notes: Optional[str] = None


class HazardReviewFindings(BaseModel):
    """Why the hazard exists, not merely that it does."""

    root_cause: Optional[str] = None
    review_notes: Optional[str] = None
    persons_exposed: Optional[int] = Field(None, ge=0)


# ══════════════════════════════════════════════════════════════════════════════
# 05 IMPROVE
# ══════════════════════════════════════════════════════════════════════════════
HIERARCHY = ("elimination", "substitution", "engineering", "administrative", "ppe")


class HazardPlanControls(BaseModel):
    """The permanent control, named at its level in the hierarchy.

    `control_hierarchy` is required rather than optional because the whole point
    of stage 05 is that elimination beats PPE. A register that lets the level go
    unrecorded cannot report how many hazards were signed off on PPE alone.
    """

    planned_controls: str = Field(..., min_length=1)
    control_hierarchy: str = Field(
        ..., description=" | ".join(HIERARCHY)
    )
    control_owner_id: Optional[int] = None
    control_due_date: Optional[date] = None
    ppe_justification: Optional[str] = Field(
        None,
        description="Why a stronger control is not reasonably practicable. "
                    "Required when control_hierarchy is 'ppe'.",
    )


class HazardSubmitVerification(BaseModel):
    """The planned control is now actually in place."""

    implementation_notes: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# 06 VERIFY
# ══════════════════════════════════════════════════════════════════════════════
class HazardVerifyControls(BaseModel):
    """Stage 06 VERIFY — did the permanent control hold?

    Distinct from HazardVerify below, which is the auditor's post-closure
    assurance check and gates nothing. This one moves the hazard between
    stages 05 and 07.
    """

    effective: bool = Field(..., description="Did the control work?")
    verification_notes: Optional[str] = Field(None, description="What was checked, and how")


# ══════════════════════════════════════════════════════════════════════════════
# 07 LEARN · 08 CLOSE
# ══════════════════════════════════════════════════════════════════════════════
class HazardLesson(BaseModel):
    """What the register learned. Recorded before closure, not as part of it."""

    lessons_learned: str = Field(..., min_length=1)


class HazardClose(BaseModel):
    closure_notes: Optional[str] = None
    lessons_learned: Optional[str] = Field(
        None, description="Accepted here too, so LEARN and CLOSE can be one action"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Generic review (retained) and auditor verification
# ══════════════════════════════════════════════════════════════════════════════
class HazardReview(BaseModel):
    """Supervisor/Manager moves a hazard through its control lifecycle.

    The pre-stage escape hatch, kept because the manager register screen and the
    mobile app both post to it. The stage verbs above are preferred: they record
    who did what at which stage, which this cannot.
    """

    register_status: Optional[str] = None
    review_notes: Optional[str] = None
    controls: Optional[str] = None
    severity: Optional[str] = None


class HazardVerify(BaseModel):
    """Auditor records that the hazard is being managed on site."""

    verification_notes: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# Responses
# ══════════════════════════════════════════════════════════════════════════════
class HazardRegisterResponse(BaseModel):
    id: int
    reference: Optional[str] = Field(
        None, description="HAZ-<id> — a display convention, not a stored code"
    )
    hazard_name: Optional[str] = None
    category_id: Optional[int] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    probability: Optional[str] = None
    # What the reporter said, kept apart from the assessor's rescoring above.
    reported_severity: Optional[str] = None
    reported_probability: Optional[str] = None
    existing_controls: Optional[str] = None
    reported_persons_exposed: Optional[int] = None
    register_status: Optional[str] = None
    location_station_id: Optional[int] = None
    location_other: Optional[str] = None
    still_present: Optional[bool] = None
    controls: Optional[str] = None
    logged_by: Optional[int] = None
    logged_at: Optional[datetime] = None
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    auditor_verified_by: Optional[int] = None
    auditor_verified_at: Optional[datetime] = None
    verification_notes: Optional[str] = None
    gps_latitude: Optional[str] = None
    gps_longitude: Optional[str] = None
    # Photos and video of the condition, as /uploads/ paths.
    evidence: List[Any] = Field(default_factory=list)

    # ── 02 ASSESS ────────────────────────────────────────────────────────────
    assessed_priority: Optional[str] = None
    assessed_label: Optional[str] = None
    risk_score: Optional[int] = None
    assessed_by: Optional[int] = None
    assessed_at: Optional[datetime] = None
    response_due_at: Optional[datetime] = None

    # ── 03 RESPOND ───────────────────────────────────────────────────────────
    interim_control: Optional[str] = None
    interim_control_by: Optional[int] = None
    interim_control_at: Optional[datetime] = None
    work_stopped: Optional[int] = None

    # ── 04 INVESTIGATE ───────────────────────────────────────────────────────
    review_started_at: Optional[datetime] = None
    root_cause: Optional[str] = None
    persons_exposed: Optional[int] = None

    # ── 05 IMPROVE ───────────────────────────────────────────────────────────
    planned_controls: Optional[str] = None
    control_hierarchy: Optional[str] = None
    control_owner_id: Optional[int] = None
    control_due_date: Optional[date] = None
    controls_planned_by: Optional[int] = None
    controls_planned_at: Optional[datetime] = None

    # ── 06 VERIFY ────────────────────────────────────────────────────────────
    controls_verified_by: Optional[int] = None
    controls_verified_at: Optional[datetime] = None
    control_verification_notes: Optional[str] = None
    verification_failures: Optional[int] = None

    # ── 07 LEARN · 08 CLOSE ──────────────────────────────────────────────────
    lessons_learned: Optional[str] = None
    lesson_captured_by: Optional[int] = None
    lesson_captured_at: Optional[datetime] = None
    closure_notes: Optional[str] = None
    closed_by: Optional[int] = None
    closed_at: Optional[datetime] = None

    # The row's own audit timestamps. `logged_at` is when the worker submitted;
    # these are when the record was written and last touched, which is not the
    # same thing for a hazard created by an import or edited on the website.
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # Position on the eight stages, derived from register_status by
    # workflow_stages.describe("hazard_register", ...) — never stored.
    stage: Optional[str] = None
    stage_number: Optional[int] = None
    stage_label: Optional[str] = None
    completed_stages: List[str] = Field(default_factory=list)
    total_stages: Optional[int] = None

    # Resolved names, so a list does not need a lookup per row.
    logged_by_name: Optional[str] = None
    reviewed_by_name: Optional[str] = None
    control_owner_name: Optional[str] = None
    # Every other actor column was an id with no name beside it, so a manager
    # reviewing a hazard could see that stage 05 had been done and not by whom.
    assessed_by_name: Optional[str] = None
    interim_control_by_name: Optional[str] = None
    controls_planned_by_name: Optional[str] = None
    controls_verified_by_name: Optional[str] = None
    lesson_captured_by_name: Optional[str] = None
    closed_by_name: Optional[str] = None
    auditor_verified_by_name: Optional[str] = None
    station_name: Optional[str] = None
    category_name: Optional[str] = None
    is_overdue: Optional[bool] = None

    model_config = {"from_attributes": True}


class HazardNextActionResponse(BaseModel):
    """Stage tracker + the one outstanding step, for one hazard."""

    hazard_id: int
    reference: str
    register_status: Optional[str] = None
    stage: Optional[str] = None
    stage_number: Optional[int] = None
    stage_label: Optional[str] = None
    is_closed: bool = False
    next_action: Optional[Dict[str, Any]] = None
    can_act: bool = False
    is_mine: bool = False
    track: List[Dict[str, Any]] = Field(default_factory=list)
