"""
Pydantic schemas for the role-based incident reporting workflow.

Flow: Worker reports → Supervisor acknowledges & investigates → Manager approves & closes
"""
from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal
from typing import Any, List, Optional

from pydantic import BaseModel, Field, computed_field

from app.services import workflow_stages


# ── Worker: Report Incident ───────────────────────────────────────────────────

class WorkerIncidentReport(BaseModel):
    """What the worker submits when reporting an incident."""
    incident_date_time: datetime
    location_station_id: Optional[int] = None
    incident_type: str = Field(..., description="Injury | Near Miss | Unsafe Act | Unsafe Condition | Property Damage | Environmental Spill")
    severity: str = Field(..., description="Minor | Moderate | Serious | Critical")
    description: str = Field(..., min_length=5)
    # Required — without it the incident has no hazard/category link, which is
    # what backs the dashboard's "Top Incident Categories" chart. Left optional
    # historically, so hazard_id silently went unset on most incidents.
    hazard_id: int
    anyone_injured: str = Field(default="No", description="Yes | No")
    injured_person_name: Optional[str] = None
    injured_body_part: Optional[str] = None
    hazard_still_present: str = Field(default="No", description="Yes | No")
    witnesses_json: Optional[List[str]] = None
    evidence_json: Optional[List[str]] = None
    gps_latitude: Optional[Decimal] = None
    gps_longitude: Optional[Decimal] = None
    number_persons_involved: Optional[int] = None

    # ── WF-03 severity decision tree inputs ───────────────────────────────────
    # `severity` above stays as the reporter's own impression, which the website
    # still displays. These three feed the system-enforced P1-P5 classification.
    # All optional: a worker reporting from the field may not know the treatment
    # level yet, and an unclassified incident is safer than a guessed one.
    treatment_level: Optional[str] = Field(
        None,
        description="Q2 — none | first_aid | medical_treatment | hospitalisation | fatality",
    )
    dangerous_occurrence: bool = Field(
        False, description="Q3 — structural collapse, explosion, major release"
    )
    worst_case_fatal: bool = Field(
        False, description="Q4 — could this plausibly have killed or injured several people?"
    )
    days_away: Optional[int] = None


# ── Supervisor: Acknowledge ───────────────────────────────────────────────────

class SupervisorAcknowledge(BaseModel):
    """Supervisor acknowledges the incident within 30 min SLA."""
    notes: Optional[str] = None


# ── Supervisor: Investigate ───────────────────────────────────────────────────

class SupervisorInvestigate(BaseModel):
    """Supervisor completes investigation with root cause analysis."""
    root_cause: str = Field(..., description="Root cause determined by 5-Why analysis")
    five_why_analysis: Optional[List[dict]] = Field(
        None, description='Array of steps: [{"why": "...", "answer": "..."}]'
    )
    immediate_cause: Optional[str] = None
    immediate_actions_taken: Optional[str] = None
    root_cause_category: Optional[str] = None
    severity_classification: str = Field(..., description="LTI | MTI | First Aid | Near Miss")
    days_away: Optional[int] = None
    # Re-runs the WF-03 decision tree with what the investigation established.
    # The supervisor usually learns the real treatment level after the reporter
    # filed, so this is where P1-P5 most often changes.
    treatment_level: Optional[str] = Field(
        None,
        description="Q2 — none | first_aid | medical_treatment | hospitalisation | fatality",
    )
    dangerous_occurrence: Optional[bool] = None
    worst_case_fatal: Optional[bool] = None
    occupational_disease: bool = False
    loss_of_consciousness: bool = False
    # CAPA details (optional — can also be created separately)
    capa_description: Optional[str] = None
    capa_responsible_person_id: Optional[int] = None
    # Optional. Left unset, WF-04's due-date rule computes it from the CAPA type.
    capa_due_date: Optional[date] = None
    # WF-04 priority matrix inputs. Without both, the CAPA still gets a type and
    # a deadline from the incident severity — just no 1-9 priority band.
    capa_severity_potential: Optional[str] = Field(None, description="low | medium | high (or 1-3)")
    capa_systemic_risk: Optional[str] = Field(None, description="low | medium | high (or 1-3)")
    capa_type: Optional[str] = Field(None, description="P1..P5 — overrides inheritance from incident severity")
    # Escalate to manager?
    escalate: bool = Field(default=False, description="Set true to escalate to manager")
    escalation_reason: Optional[str] = None


# ── Supervisor: Escalate ──────────────────────────────────────────────────────

class SupervisorEscalate(BaseModel):
    """Explicitly escalate an incident to manager."""
    escalation_reason: str = Field(..., min_length=3)
    escalated_to_manager_id: Optional[int] = None


# ── Manager: Approve Investigation ───────────────────────────────────────────

class ManagerApproveInvestigation(BaseModel):
    """Manager approves or rejects the supervisor's investigation."""
    decision: str = Field(..., description="approved | rejected")
    notes: Optional[str] = None


# ── Manager: Verify CAPA effectiveness (stage 06) ─────────────────────────────

class ManagerVerifyEffectiveness(BaseModel):
    """Stage 06 VERIFY — did the corrective action actually work?

    `effective=False` sends the incident back to IMPROVE: an action that did not
    work means the problem is still live, and closing it would be a lie.
    """
    effective: bool = Field(..., description="Did the CAPA hold?")
    verification_notes: Optional[str] = Field(None, description="What was checked, and how")


# ── Manager: Close Incident ───────────────────────────────────────────────────

class ManagerCloseIncident(BaseModel):
    """Manager formally closes the incident."""
    closure_notes: Optional[str] = None
    regulatory_notified: str = Field(default="No", description="Yes | No")
    lessons_learned: Optional[str] = None
    communicated_to_teams: str = Field(default="No", description="Yes | No")


# ── Supervisor/Manager: Complete a CAPA action ────────────────────────────────

class CapaComplete(BaseModel):
    """Marks a corrective action as done. effectiveness_rating is 1-5."""
    effectiveness_rating: Optional[int] = None


# ── Response Schemas ──────────────────────────────────────────────────────────

class StageInfo(BaseModel):
    """Where this incident sits on the eight-stage lifecycle.

    Derived from workflow_status on the way out rather than stored, so it can
    never disagree with the status the rest of the system reads.
    """
    stage: Optional[str] = None
    stage_number: Optional[int] = None
    stage_label: Optional[str] = None
    stage_description: Optional[str] = None
    total_stages: int = 8
    completed_stages: List[str] = Field(default_factory=list)
    is_closed: bool = False


class _StageMixin(BaseModel):
    """Adds the derived `stage` block to any response carrying a status."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def stage(self) -> StageInfo:
        d = workflow_stages.describe("incident", getattr(self, "workflow_status", None))
        return StageInfo(
            stage=d["stage"],
            stage_number=d["stage_number"],
            stage_label=d["stage_label"],
            stage_description=d["stage_description"],
            total_stages=d["total_stages"],
            completed_stages=d["completed_stages"],
            is_closed=d["is_closed"],
        )


class IncidentWorkflowResponse(_StageMixin):
    """Full incident response with workflow fields."""
    id: int
    organisation_id: Optional[int] = None
    report_date: Optional[date] = None
    incident_date_time: Optional[datetime] = None
    location_station_id: Optional[int] = None
    incident_type: Optional[str] = None
    severity: Optional[str] = None
    number_persons_involved: Optional[int] = None
    description: Optional[str] = None
    immediate_cause: Optional[str] = None
    root_cause: Optional[str] = None
    hazard_id: Optional[int] = None
    permit_active: Optional[str] = None
    control_failure: Optional[str] = None
    reported_by: Optional[int] = None
    investigation_status: Optional[str] = None
    capa_generated: Optional[str] = None
    days_away: Optional[int] = None
    root_cause_category: Optional[str] = None

    # Workflow
    workflow_status: Optional[str] = None
    assigned_supervisor_id: Optional[int] = None
    escalated_to_manager_id: Optional[int] = None
    escalation_reason: Optional[str] = None

    # Timestamps
    reported_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    investigation_started_at: Optional[datetime] = None
    investigation_completed_at: Optional[datetime] = None
    escalated_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # Manager closure
    closure_notes: Optional[str] = None
    regulatory_notified: Optional[str] = None
    lessons_learned: Optional[str] = None
    communicated_to_teams: Optional[str] = None
    manager_signature: Optional[str] = None

    # Display labels for the foreign keys above, resolved on read by
    # get_incident_detail. A reviewer needs the station's name, not its id.
    location_station_name: Optional[str] = None
    hazard_name: Optional[str] = None
    reported_by_name: Optional[str] = None
    supervisor_name: Optional[str] = None

    # The corrective actions raised during the investigation. Travels with the
    # record so an approver can see what they are signing off, not just that
    # something exists.
    capa_actions: List[dict] = Field(default_factory=list)

    # Worker extras
    anyone_injured: Optional[str] = None
    injured_person_name: Optional[str] = None
    injured_body_part: Optional[str] = None
    hazard_still_present: Optional[str] = None
    witnesses_json: Optional[Any] = None
    evidence_json: Optional[Any] = None
    gps_latitude: Optional[Decimal] = None
    gps_longitude: Optional[Decimal] = None

    # Supervisor investigation
    five_why_analysis: Optional[Any] = None
    immediate_actions_taken: Optional[str] = None
    supervisor_signature: Optional[str] = None
    severity_classification: Optional[str] = None

    # WF-03 severity classification
    severity_priority: Optional[str] = None
    severity_label: Optional[str] = None
    treatment_level: Optional[str] = None
    dangerous_occurrence: Optional[bool] = None
    worst_case_fatal: Optional[bool] = None
    is_hipo: Optional[bool] = None
    is_recurring_pattern: Optional[bool] = None
    requires_systemic_rca: Optional[bool] = None
    severity_trace: Optional[str] = None
    severity_classified_at: Optional[datetime] = None
    investigation_due_at: Optional[datetime] = None
    min_investigator: Optional[str] = None

    # Appendix A statutory notification
    statutory_reportable: Optional[bool] = None
    statutory_jurisdiction: Optional[str] = None
    statutory_regulator: Optional[str] = None
    statutory_obligations: Optional[Any] = None
    statutory_due_at: Optional[datetime] = None
    statutory_summary: Optional[str] = None
    statutory_authorised_by: Optional[int] = None
    statutory_authorised_at: Optional[datetime] = None
    statutory_reference: Optional[str] = None

    # Stage 06 VERIFY — the manager's confirmation that the CAPA held. Kept
    # separate from the auditor trio below, which is a post-closure review.
    capa_verified_by: Optional[int] = None
    capa_verified_at: Optional[datetime] = None
    capa_verification_notes: Optional[str] = None
    capa_verification_failures: Optional[int] = None

    # Auditor close-out (stage 08). These were written by POST /{id}/verify but
    # never exposed here, so the detail endpoint the app reads reported an
    # audited incident as unverified.
    auditor_verified_by: Optional[int] = None
    auditor_verified_at: Optional[datetime] = None
    verification_notes: Optional[str] = None

    model_config = {"from_attributes": True}


class IncidentListItem(_StageMixin):
    """Lighter response for list views."""
    id: int
    incident_date_time: Optional[datetime] = None
    incident_type: Optional[str] = None
    severity: Optional[str] = None
    description: Optional[str] = None
    workflow_status: Optional[str] = None
    reported_by: Optional[int] = None
    reported_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    location_station_id: Optional[int] = None
    anyone_injured: Optional[str] = None
    severity_classification: Optional[str] = None
    created_at: Optional[datetime] = None

    # The list view is what the supervisor and manager queues render, so the
    # priority, the HIPO flag and both due dates need to be visible without
    # opening each record.
    severity_priority: Optional[str] = None
    severity_label: Optional[str] = None
    is_hipo: Optional[bool] = None
    is_recurring_pattern: Optional[bool] = None
    investigation_due_at: Optional[datetime] = None
    statutory_reportable: Optional[bool] = None
    statutory_due_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
