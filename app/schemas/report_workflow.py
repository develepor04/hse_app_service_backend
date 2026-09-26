"""Request/response schemas shared by the near-miss, unsafe-act and risk workflows.

Mirrors app/schemas/incident_workflow.py. Kept separate from it so that changing one
report type's contract can never alter the incident contract the website depends on.
"""
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════════════════════════
# WORKER — submission
# ══════════════════════════════════════════════════════════════════════════════
class WitnessRef(BaseModel):
    """A witness picked from the employee register rather than typed."""

    name: str
    employee_id: Optional[int] = None


class WorkerReportBase(BaseModel):
    """Fields every worker report form sends, whatever the type."""

    description: str = Field(..., min_length=1)
    severity: str = "medium"
    location: Optional[str] = None
    location_station_id: Optional[int] = None
    observed_date_time: Optional[datetime] = None
    hazard_still_present: Optional[str] = None
    # A witness is either a name typed in — a contractor, a visitor, someone
    # not on the payroll — or a real employee picked from the register, in
    # which case their id comes with it. Accepting both keeps the link where
    # one exists instead of flattening everybody to a string, which is what
    # made the admin trail say witnesses "carry no employee ID".
    witnesses: Optional[List[Union[str, WitnessRef]]] = None
    photos: Optional[List[str]] = None
    gps_latitude: Optional[str] = None
    gps_longitude: Optional[str] = None


class NearMissReport(WorkerReportBase):
    # Each takes a listed option or whatever the worker typed under "Other" —
    # one column holds both, so nothing is lost and no companion "…_is_other"
    # flag has to be kept in step with it.
    potential_consequence: Optional[str] = None
    underlying_cause: Optional[str] = None
    hazard_id: Optional[int] = None
    # Set only when the place or the hazard is not on the register, in which
    # case location_station_id / hazard_id are left unset.
    location_other: Optional[str] = None
    hazard_other: Optional[str] = None
    control_failure: Optional[str] = None
    capa_escalation: Optional[str] = None
    # The form's own field name. Kept as the client sends it rather than
    # renamed to match the column, because the offline queue has stored bodies
    # using this key and a rename would strand them.
    preventative_suggestion: Optional[str] = None


class UnsafeActReport(WorkerReportBase):
    act_type: Optional[str] = None
    person_observed: Optional[str] = None
    rule_violated: Optional[str] = None
    corrective_advice_given: Optional[str] = None


class RiskReportCreate(WorkerReportBase):
    risk_title: Optional[str] = None
    risk_category: Optional[str] = None
    likelihood: Optional[str] = None
    consequence: Optional[str] = None
    risk_score: Optional[int] = None
    existing_controls: Optional[str] = None
    suggested_controls: Optional[str] = None
    hazard_id: Optional[int] = None
    # The same "Other" pair near misses carry, and the same two context
    # questions. The columns have existed on risk_reports since 068; nothing
    # could reach them because the schema had no field for them.
    potential_consequence: Optional[str] = None
    underlying_cause: Optional[str] = None
    location_other: Optional[str] = None
    hazard_other: Optional[str] = None

    # ── WF-01 mandatory uplift flags ──────────────────────────────────────────
    # All four default to False, so a client that does not send them scores
    # exactly as before. night_shift is derived server-side from
    # observed_date_time when the client omits it — see risk_workflow._build_row.
    no_valid_rams: bool = False
    new_worker: bool = False
    night_shift: Optional[bool] = None
    temporary_control: bool = False


# ══════════════════════════════════════════════════════════════════════════════
# SUPERVISOR — acknowledge / investigate / escalate
# ══════════════════════════════════════════════════════════════════════════════
class SupervisorAcknowledgeReport(BaseModel):
    notes: Optional[str] = None


class SupervisorInvestigateReport(BaseModel):
    root_cause: Optional[str] = None
    five_why_analysis: Optional[Dict[str, Any]] = None
    immediate_actions_taken: Optional[str] = None
    supervisor_signature: Optional[str] = None
    severity: Optional[str] = None

    # ── Stage 05 IMPROVE ──────────────────────────────────────────────────────
    # A corrective action raised here is what makes IMPROVE and VERIFY
    # occupiable: without one there is nothing to improve and nothing whose
    # effectiveness could be confirmed, and the record goes 04 -> 07 directly.
    capa_description: Optional[str] = None
    capa_responsible_person_id: Optional[int] = None
    # Omit to let the WF-04 rule compute it from the CAPA type.
    capa_due_date: Optional[date] = None
    capa_severity_potential: Optional[str] = Field(None, description="low | medium | high (or 1-3)")
    capa_systemic_risk: Optional[str] = Field(None, description="low | medium | high (or 1-3)")
    capa_type: Optional[str] = Field(None, description="P1..P5 — overrides inheritance from severity")


class ManagerVerifyReportEffectiveness(BaseModel):
    """Stage 06 VERIFY — did the corrective action actually work?

    `effective=False` returns the record to IMPROVE and reopens its actions: a
    control that did not hold means the hazard is still live.
    """
    effective: bool = Field(..., description="Did the CAPA hold?")
    verification_notes: Optional[str] = Field(None, description="What was checked, and how")


class ReportCapaComplete(BaseModel):
    """Marks a corrective action done. effectiveness_rating is 1-5."""
    effectiveness_rating: Optional[int] = None


class SupervisorEscalateReport(BaseModel):
    escalation_reason: str = Field(..., min_length=1)
    escalated_to_manager_id: Optional[int] = None


# ══════════════════════════════════════════════════════════════════════════════
# MANAGER — approve / close
# ══════════════════════════════════════════════════════════════════════════════
class ManagerApproveReport(BaseModel):
    approved: bool = True
    notes: Optional[str] = None


class ManagerCloseReport(BaseModel):
    closure_notes: Optional[str] = None
    lessons_learned: Optional[str] = None
    manager_signature: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# RESPONSES
# ══════════════════════════════════════════════════════════════════════════════
class ReportWorkflowResponse(BaseModel):
    """Full record. Type-specific columns ride along in `details` so one response
    model can serve all three workflows without leaking another type's fields."""

    id: int
    report_type: str
    workflow_status: Optional[str] = None
    severity: Optional[str] = None
    description: Optional[str] = None
    location_station_id: Optional[int] = None
    reported_by: Optional[int] = None

    # Resolved on the single-record read only; the list responses leave these
    # None rather than pay for a lookup per row on a queue that shows neither.
    reported_by_name: Optional[str] = None
    station_name: Optional[str] = None
    # Whoever the reporter named as having seen it. Stored since the report
    # forms grew a witness picker, never sent back until now.
    witnesses: List[Any] = []
    # Photos and videos the reporter attached, as /uploads/ paths.
    evidence: List[Any] = []
    hazard_still_present: Optional[str] = None
    report_date: Optional[date] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # The reviewers' own work, beyond root_cause and closure_notes.
    # A JSON column, and the two writers disagree about its shape: the
    # investigate payload types it as a dict ({"whys": [...]}) while older rows
    # hold a bare list. Typed loosely so neither shape 500s on the way out; the
    # card normalises both to five lines.
    five_why_analysis: Optional[Any] = None
    lessons_learned: Optional[str] = None
    supervisor_signature: Optional[str] = None
    manager_signature: Optional[str] = None
    investigation_started_at: Optional[datetime] = None
    assessed_at: Optional[datetime] = None
    capa_verified_at: Optional[datetime] = None
    capa_verification_notes: Optional[str] = None
    capa_verification_failures: Optional[int] = None
    assigned_supervisor_name: Optional[str] = None
    escalated_to_manager_name: Optional[str] = None
    capa_verified_by_name: Optional[str] = None
    auditor_verified_by_name: Optional[str] = None
    observed_at: Optional[datetime] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None

    reported_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    investigation_completed_at: Optional[datetime] = None
    escalated_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None

    root_cause: Optional[str] = None
    immediate_actions_taken: Optional[str] = None
    escalation_reason: Optional[str] = None
    closure_notes: Optional[str] = None

    # Step 4 — independent assurance
    auditor_verified_by: Optional[int] = None
    auditor_verified_at: Optional[datetime] = None
    verification_result: Optional[str] = None
    verification_notes: Optional[str] = None

    # ── Stage 02 ASSESS ───────────────────────────────────────────────────────
    # `severity` above is what the reporter picked. `assessed_priority` is what
    # the deterministic assessor concluded, on the one P1-P5 scale shared by
    # every event family.
    assessed_priority: Optional[str] = None
    assessed_label: Optional[str] = None
    is_hipo: Optional[bool] = None
    is_recurring_pattern: Optional[bool] = None
    requires_systemic_rca: Optional[bool] = None
    response_due_at: Optional[datetime] = None
    min_investigator: Optional[str] = None
    assessment_trace: Optional[str] = None

    # ── Position in the eight stages ──────────────────────────────────────────
    stage: Optional[str] = None
    stage_number: Optional[int] = None
    stage_label: Optional[str] = None
    completed_stages: List[str] = Field(default_factory=list)
    total_stages: Optional[int] = None

    details: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class ReportListItem(BaseModel):
    id: int
    report_type: str
    workflow_status: Optional[str] = None
    severity: Optional[str] = None
    description: Optional[str] = None
    location_station_id: Optional[int] = None
    reported_by: Optional[int] = None
    reported_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    # Queues rank on the assessed priority and the response deadline, not on the
    # reporter's severity guess.
    assessed_priority: Optional[str] = None
    is_hipo: Optional[bool] = None
    response_due_at: Optional[datetime] = None
    # Enough to draw the eight-stage rail on a queue card without opening the
    # record — the detail response carries the identical five fields.
    stage: Optional[str] = None
    stage_number: Optional[int] = None
    stage_label: Optional[str] = None
    completed_stages: List[str] = Field(default_factory=list)
    total_stages: Optional[int] = None

    model_config = {"from_attributes": True}


class ReportVerify(BaseModel):
    """Step 4 of the workflow chain — the auditor verifies independently.

    "Confirms on site that the control is real. Verification is recorded
    against the original record — the independent assurance layer in the audit
    trail." The verdict is deliberately separate from the workflow status: an
    auditor records what they found, they do not move the record.
    """

    verification_result: str = Field(..., pattern="^(verified|not_verified|partial)$")
    verification_notes: Optional[str] = None
