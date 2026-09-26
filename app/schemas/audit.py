"""Request/response schemas for WF-05 — schedule to verified closure.

The ten steps each have their own payload rather than one fat update endpoint,
because the steps are not interchangeable: an opening meeting record cannot be
posted after the closing meeting, findings cannot be re-classified once locked,
and a report cannot be issued without a signature. A single PATCH would make all
three of those the caller's problem.
"""
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════════════════════════
# Checklist
# ══════════════════════════════════════════════════════════════════════════════

class ChecklistItemIn(BaseModel):
    """One checklist line, in either vocabulary.

    `response` accepts the rubric values (full | partial | none | na) and the
    legacy pass/fail/na an older mobile build still sends. The scoring service
    normalises both, so an app that has not been updated still submits a
    correctly scored audit.
    """
    id: Optional[int] = None
    seq: Optional[int] = None
    section: Optional[str] = None
    title: Optional[str] = None
    question: Optional[str] = None
    clause: Optional[str] = None
    is_critical: bool = False
    response: Optional[str] = None
    remarks: Optional[str] = None
    classification: Optional[str] = None
    photo_attached: bool = False
    evidence_count: int = 0
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None
    # Legacy alias. Older builds flag a stop-work item as `critical`; it means
    # the same thing as is_critical and is folded into it on the way in.
    critical: bool = False


class ChecklistItemOut(ChecklistItemIn):
    points_earned: Optional[int] = None
    points_possible: Optional[int] = None
    answered_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ItemRespond(BaseModel):
    """Step 05 · one answer, logged live as the auditor walks."""
    response: str = Field(..., description="full | partial | none | na")
    remarks: Optional[str] = None
    classification: Optional[str] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None


class ItemRespondResult(BaseModel):
    item: ChecklistItemOut
    answered: int
    total: int
    running_score: float
    running_band: str
    # Set when a critical item scored zero: the alert has already been raised by
    # the time this response is read, and the app shows it rather than deciding it.
    alert: Optional[str] = None
    is_repeat: bool = False


# ══════════════════════════════════════════════════════════════════════════════
# Steps 01-02 PLAN
# ══════════════════════════════════════════════════════════════════════════════

class AuditCreate(BaseModel):
    title: str = Field(..., min_length=1)
    checklist_type: Optional[str] = None
    site_id: Optional[int] = None
    site_name: Optional[str] = None
    department: Optional[str] = None
    shift: Optional[str] = None
    auditor_id: Optional[int] = None
    scheduled_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    priority: str = "Med"
    trigger_type: Optional[str] = "scheduled_programme"
    audit_scope: Optional[str] = None
    auditee_manager_id: Optional[int] = None
    previous_audit_id: Optional[int] = None
    items: Optional[List[ChecklistItemIn]] = None


class TeamAssign(BaseModel):
    """Step 02 · the Safety Manager names the lead and the team.

    `auditee_manager_id` is required in practice, not decoratively: the auditee
    is the one who gets the two weeks' notice, and there is nobody to notify
    without it.
    """
    lead_auditor_id: int
    team_member_ids: List[int] = Field(default_factory=list)
    auditee_manager_id: Optional[int] = None
    notes: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# Step 04 · opening meeting
# ══════════════════════════════════════════════════════════════════════════════

class OpeningMeeting(BaseModel):
    scope: str = Field(..., min_length=1, description="What is in and out of scope")
    method: str = Field(..., min_length=1, description="How the audit will be conducted")
    sampling_approach: str = Field(..., min_length=1, description="What will be sampled and how")
    attendees: List[str] = Field(default_factory=list)
    auditee_present: bool = True
    notes: Optional[str] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None


# ══════════════════════════════════════════════════════════════════════════════
# Step 06 · evidence
# ══════════════════════════════════════════════════════════════════════════════

class EvidenceCreate(BaseModel):
    checklist_item_id: Optional[int] = None
    finding_id: Optional[int] = None
    kind: str = "photo"                       # photo | video | document | note | scan | interview
    file_url: Optional[str] = None
    caption: Optional[str] = None
    scanned_ref: Optional[str] = None         # QR / barcode payload
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None
    captured_at: Optional[datetime] = None
    # A worker interview: who was asked, what they were asked to demonstrate, and
    # whether their competence card checked out against the matrix.
    subject_employee_id: Optional[int] = None
    subject_name: Optional[str] = None
    interview_prompt: Optional[str] = None
    competence_verified: Optional[bool] = None


class EvidenceOut(BaseModel):
    id: int
    audit_id: int
    checklist_item_id: Optional[int] = None
    finding_id: Optional[int] = None
    kind: str
    file_url: Optional[str] = None
    caption: Optional[str] = None
    scanned_ref: Optional[str] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None
    captured_at: Optional[datetime] = None
    subject_employee_id: Optional[int] = None
    subject_name: Optional[str] = None
    interview_prompt: Optional[str] = None
    competence_verified: Optional[bool] = None

    class Config:
        from_attributes = True


# ══════════════════════════════════════════════════════════════════════════════
# Step 07 · classify and score
# ══════════════════════════════════════════════════════════════════════════════

class FindingIn(BaseModel):
    checklist_item_id: Optional[int] = None
    section: Optional[str] = None
    title: str = Field(..., min_length=1)
    description: Optional[str] = None
    clause: Optional[str] = None
    classification: str = Field(..., description="conformance | observation | minor_nc | major_nc | critical")
    corrective_action_due: Optional[date] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None


class FindingOut(BaseModel):
    id: int
    audit_id: int
    checklist_item_id: Optional[int] = None
    finding_ref: Optional[str] = None
    section: Optional[str] = None
    title: str
    description: Optional[str] = None
    clause: Optional[str] = None
    classification: str
    auto_classified: bool = False
    is_repeat: bool = False
    repeat_of_audit_id: Optional[int] = None
    corrective_action_due: Optional[date] = None
    capa_id: Optional[int] = None
    status: str
    verified_at: Optional[datetime] = None
    verification_notes: Optional[str] = None
    closed_at: Optional[datetime] = None
    evidence: List[EvidenceOut] = Field(default_factory=list)

    class Config:
        from_attributes = True


class ClassifySubmit(BaseModel):
    """Step 07 · the auditor's judgement on every finding, plus the arithmetic.

    Items may be sent in the same call for an app that worked offline and is
    catching up: the answers and their classifications arrive together rather
    than as ten queued PATCHes that must not be reordered.
    """
    items: List[ChecklistItemIn] = Field(default_factory=list)
    findings: List[FindingIn] = Field(default_factory=list)
    shift: Optional[str] = None
    notes: Optional[str] = None


class ScoreBreakdown(BaseModel):
    score: float
    band: str
    band_label: str
    points_earned: int
    points_possible: int
    assessed: int
    not_applicable: int
    unanswered: int
    overall_rating: str
    explanation: str
    sections: List[Dict[str, Any]] = Field(default_factory=list)
    counts: Dict[str, int] = Field(default_factory=dict)


# ══════════════════════════════════════════════════════════════════════════════
# Step 08 · closing meeting
# ══════════════════════════════════════════════════════════════════════════════

class ClosingMeeting(BaseModel):
    """The auditee confirms factual accuracy, and the findings lock.

    Both signatures are captured on the device before anyone leaves site. The
    signature is a data URI or a stored path — whichever the app produced — and
    the name is captured separately so a report can name who signed even if the
    image is unreadable.
    """
    attendees: List[str] = Field(default_factory=list)
    factual_accuracy_confirmed: bool = Field(
        ..., description="Auditee agrees the findings are factually accurate"
    )
    agreed_timeframes: Dict[str, str] = Field(
        default_factory=dict, description="finding_id -> agreed corrective action date"
    )
    auditee_signature: Optional[str] = None
    auditee_signed_name: Optional[str] = None
    auditor_signature: Optional[str] = None
    auditor_signed_name: Optional[str] = None
    notes: Optional[str] = None
    disputes: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# Step 09 · issue the report
# ══════════════════════════════════════════════════════════════════════════════

class IssueReport(BaseModel):
    """Signing is what distributes the report and raises the corrective actions."""
    auditor_signature: str = Field(..., min_length=1, description="The report cannot be issued without the auditor's signature")
    auditor_signed_name: str = Field(..., min_length=1)
    summary: Optional[str] = None


class ReportApproval(BaseModel):
    """The Safety Manager reviews and approves before wider distribution.

    Approving is not re-signing: the auditor's signature already made the report
    real and the corrective actions already exist. This releases it past the site.
    """
    approved: bool = True
    notes: Optional[str] = None


class ReportOut(BaseModel):
    audit_id: int
    report_ref: Optional[str] = None
    issued_at: Optional[datetime] = None
    title: str
    site_name: Optional[str] = None
    checklist_type: Optional[str] = None
    conducted_on: Optional[datetime] = None
    lead_auditor: Optional[str] = None
    score: ScoreBreakdown
    findings: List[FindingOut] = Field(default_factory=list)
    benchmark: Dict[str, Any] = Field(default_factory=dict)
    clause_map: List[Dict[str, Any]] = Field(default_factory=list)
    escalations: List[Dict[str, Any]] = Field(default_factory=list)
    distributed_to: List[int] = Field(default_factory=list)
    signed_by: Optional[str] = None
    auditee_signed_by: Optional[str] = None
    auditor_signature: Optional[str] = None
    auditee_signature: Optional[str] = None
    # Every photo, video and note captured on the walk, not only the ones that
    # happen to hang off a finding. The report listed a count and nothing else,
    # so a conformance evidenced by a photograph showed no photograph, and a
    # video recorded on site existed only on the phone that took it.
    evidence: List[EvidenceOut] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# Step 10 · close out
# ══════════════════════════════════════════════════════════════════════════════

class FindingVerify(BaseModel):
    """One finding, verified closed on site — or sent back."""
    effective: bool = Field(..., description="Was the corrective action actually effective?")
    verification_notes: Optional[str] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None


class AuditVerify(BaseModel):
    """Legacy whole-audit verification, kept so existing clients keep working."""
    effective: bool = Field(..., description="Did the actions resolve the findings?")
    verification_notes: Optional[str] = None


class AuditSubmit(BaseModel):
    """Legacy one-shot submit. Superseded by step 07 classify, still accepted."""
    items: List[ChecklistItemIn] = Field(default_factory=list)
    shift: Optional[str] = None
    compliance_score: Optional[int] = None
    notes: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# The audit itself
# ══════════════════════════════════════════════════════════════════════════════

class StepState(BaseModel):
    """Where the audit sits on the ten steps."""
    number: int
    key: str
    phase: str            # PLAN | PREPARE | CONDUCT | CLASSIFY | AGREE | REPORT | CLOSE
    label: str
    owner: str            # auditor | worker | supervisor | safety_manager | admin | system
    owner_label: Optional[str] = None
    state: str            # done | active | blocked | todo
    automatic: bool = False
    hard_stop: bool = False
    on_mobile: bool = False
    detail: Optional[str] = None


class AuditResponse(BaseModel):
    id: int
    organisation_id: Optional[int] = None
    audit_ref: Optional[str] = None
    title: str
    checklist_type: Optional[str] = None
    site_id: Optional[int] = None
    site_name: Optional[str] = None
    department: Optional[str] = None
    shift: Optional[str] = None
    auditor_id: Optional[int] = None
    scheduled_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    status: str
    priority: Optional[str] = None
    progress: Optional[int] = None
    compliance_score: Optional[int] = None
    findings: List[ChecklistItemOut] = Field(default_factory=list)
    submitted_at: Optional[datetime] = None

    # ── WF-05 ───────────────────────────────────────────────────────────────
    trigger_type: Optional[str] = None
    trigger_label: Optional[str] = None
    audit_scope: Optional[str] = None
    risk_band: Optional[str] = None
    site_score: Optional[float] = None
    audit_team: List[Dict[str, Any]] = Field(default_factory=list)
    auditee_manager_id: Optional[int] = None
    auditee_notified_at: Optional[datetime] = None
    notice_due_date: Optional[date] = None
    brief_pack_generated_at: Optional[datetime] = None
    brief_pack_reviewed_at: Optional[datetime] = None
    opening_meeting: Optional[Dict[str, Any]] = None
    opening_meeting_at: Optional[datetime] = None
    closing_meeting: Optional[Dict[str, Any]] = None
    closing_meeting_at: Optional[datetime] = None
    auditee_confirmed_at: Optional[datetime] = None
    auditee_signed_name: Optional[str] = None
    # The drawn signatures, as the device captured them.
    #
    # They have been stored since the closing meeting endpoint was written and
    # read by nothing: the response carried only the typed name, so the console
    # could say who signed and never show the signature. The whole point of the
    # pad being on the phone is that signing happens on site before anyone
    # leaves, and the record of it belongs wherever the audit is reviewed.
    auditee_signature: Optional[str] = None
    findings_locked_at: Optional[datetime] = None
    findings_locked: bool = False
    score_band: Optional[str] = None
    overall_rating: Optional[str] = None
    section_scores: List[Dict[str, Any]] = Field(default_factory=list)
    finding_counts: Dict[str, int] = Field(default_factory=dict)
    classified_findings: List[FindingOut] = Field(default_factory=list)
    auditor_signed_name: Optional[str] = None
    auditor_signature: Optional[str] = None
    report_ref: Optional[str] = None
    report_issued_at: Optional[datetime] = None
    report_approved_at: Optional[datetime] = None
    report_approval_notes: Optional[str] = None
    re_audit_required: bool = False
    re_audit_reason: Optional[str] = None
    re_audit_due_date: Optional[date] = None
    # The trigger fires automatically; the decision is the Safety Manager's.
    re_audit_decision: Optional[str] = None
    re_audit_decided_at: Optional[datetime] = None
    re_audit_decision_note: Optional[str] = None
    re_audit_audit_id: Optional[int] = None
    # Wider release, owned by the Admin and gated on the Safety Manager's approval.
    distribution_scope: Optional[str] = None
    distributed_beyond_site_at: Optional[datetime] = None
    template_id: Optional[int] = None
    generated_by_programme: bool = False
    reminder_sent_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    open_finding_count: int = 0

    # The ten steps, and which one is waiting.
    steps: List[StepState] = Field(default_factory=list)
    current_step: Optional[int] = None
    current_step_label: Optional[str] = None

    # The eight-stage position every other family reports, kept unchanged.
    stage: Optional[str] = None
    stage_number: Optional[int] = None
    stage_label: Optional[str] = None
    completed_stages: List[str] = Field(default_factory=list)
    total_stages: Optional[int] = None

    class Config:
        from_attributes = True


class ProgrammeRow(BaseModel):
    site_id: Optional[int] = None
    site_name: Optional[str] = None
    risk_band: str
    band_label: Optional[str] = None
    site_score: Optional[float] = None
    qualifying: Optional[str] = None
    inspection_frequency: Optional[str] = None
    audit_frequency: Optional[str] = None
    next_inspection_due: Optional[date] = None
    next_audit_due: Optional[date] = None
    last_audit_at: Optional[datetime] = None
    re_audit_trigger: Optional[str] = None
    overdue: bool = False
    # Computed is not the same as authorised — see the two stamps in migration 065.
    programme_year: Optional[int] = None
    authorised_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    generated_at: Optional[datetime] = None
    generated_count: int = 0
    scope_concerns: Optional[str] = None

    class Config:
        from_attributes = True


# ══════════════════════════════════════════════════════════════════════════════
# Web console · checklist templates (Admin)
# ══════════════════════════════════════════════════════════════════════════════

class TemplateItemIn(BaseModel):
    seq: Optional[int] = None
    section: Optional[str] = None
    title: str = Field(..., min_length=1)
    question: Optional[str] = None
    clause: Optional[str] = None
    is_critical: bool = False


class TemplateItemOut(TemplateItemIn):
    id: int

    class Config:
        from_attributes = True


class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1)
    checklist_type: Optional[str] = None
    description: Optional[str] = None
    standard: Optional[str] = None
    is_default: bool = False
    items: List[TemplateItemIn] = Field(default_factory=list)


class TemplateUpdate(BaseModel):
    """Supersedes rather than edits.

    A template is never rewritten in place: audits already conducted point at it,
    and the report has to be able to say what was actually asked. Every field is
    optional — omitting one carries it forward to the new version.
    """
    name: Optional[str] = None
    checklist_type: Optional[str] = None
    description: Optional[str] = None
    standard: Optional[str] = None
    is_default: Optional[bool] = None
    items: Optional[List[TemplateItemIn]] = None


class TemplateOut(BaseModel):
    id: int
    organisation_id: Optional[int] = None
    name: str
    checklist_type: Optional[str] = None
    description: Optional[str] = None
    standard: Optional[str] = None
    version: int
    is_active: bool
    is_default: bool
    items: List[TemplateItemOut] = Field(default_factory=list)
    audits_using: int = 0

    class Config:
        from_attributes = True


# ══════════════════════════════════════════════════════════════════════════════
# Web console · the programme (Safety Manager authorises, Admin approves)
# ══════════════════════════════════════════════════════════════════════════════

class ProgrammeAuthorise(BaseModel):
    """The Safety Manager authorises the programme for one site."""
    authorised: bool = True
    note: Optional[str] = None
    scope_concerns: Optional[str] = Field(
        None, description="A specific concern to include in the scope of these audits",
    )


class ProgrammeApprove(BaseModel):
    """The Admin approves the calendar across all sites."""
    approved: bool = True
    site_ids: Optional[List[int]] = Field(
        None, description="Omit to approve every site in the organisation",
    )


class CalendarGenerate(BaseModel):
    year: Optional[int] = None
    site_id: Optional[int] = None
    checklist_type: Optional[str] = None
    require_authorisation: bool = True


class GenerationOut(BaseModel):
    site_id: Optional[int] = None
    site_name: Optional[str] = None
    risk_band: str
    inspections_created: int
    audits_created: int
    skipped_existing: int
    total: int
    reason: Optional[str] = None
    created_ids: List[int] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# Web console · the re-audit decision and distribution
# ══════════════════════════════════════════════════════════════════════════════

class ReAuditDecision(BaseModel):
    """The Safety Manager owns this. The trigger fires; the decision is theirs."""
    decision: str = Field(..., description="scheduled | waived")
    note: Optional[str] = None
    scheduled_date: Optional[datetime] = Field(
        None, description="Required when scheduling — creates the re-audit",
    )
    auditor_id: Optional[int] = None


class DistributeReport(BaseModel):
    """The Admin owns distribution beyond the site."""
    scope: str = Field("organisation", description="site | organisation | external")
    recipient_employee_ids: List[int] = Field(default_factory=list)
    note: Optional[str] = None


class AuditorRegisterRow(BaseModel):
    """Who may audit, and what they are qualified to do."""
    user_id: int
    employee_id: Optional[int] = None
    name: Optional[str] = None
    email: Optional[str] = None
    is_active: bool = True
    audits_assigned: int = 0
    audits_open: int = 0
    audits_closed: int = 0
    average_score: Optional[float] = None
    last_audit_at: Optional[datetime] = None
    qualifications: List[Dict[str, Any]] = Field(default_factory=list)
    expired_qualifications: int = 0
