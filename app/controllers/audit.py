"""WF-05 Audit, Inspection & Compliance Monitoring — schedule to verified closure.

    01 PLAN      Schedule generated      system      automatic
    02 PLAN      Team assigned           safety mgr  hard stop
    03 PREPARE   Pre-audit prep          auditor
    04 CONDUCT   Opening meeting         auditor
    05 CONDUCT   Field inspection        auditor     hard stop on a critical zero
    06 CONDUCT   Evidence captured       auditor
    07 CLASSIFY  Findings & score        auditor     hard stop
    08 AGREE     Closing meeting         auditor     hard stop — supervisor confirms
    09 REPORT    Report issued           auditor     hard stop — signature required
    10 CLOSE     Findings tracked out    system      hard stop — every action verified

Steps 4 to 8 run in the field on the phone. Steps 1, 2, 9 and 10 are the web
console: schedule the programme, review and distribute the report.

`status` remains the field the rest of the system reads, and it is recomputed
from the actual facts after every transition (see `audit_steps.status_for`) so
the ten-step position and the eight-stage position cannot drift apart.
"""
import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.controllers.workflow_common import employee_id_for
from app.models.audit import (
    Audit,
    AuditChecklistItem,
    AuditChecklistTemplate,
    AuditEvidence,
    AuditFinding,
    AuditProgramme,
)
from app.services import (
    audit_brief,
    audit_calendar,
    audit_escalation,
    audit_programme,
    audit_scoring,
    audit_steps,
    audit_templates,
    audit_trends,
    capa_notify,
    media_storage,
    workflow_stages,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

from app.schemas.audit import (
    AuditCreate,
    AuditResponse,
    AuditSubmit,
    AuditVerify,
    ChecklistItemIn,
    ClassifySubmit,
    ClosingMeeting,
    EvidenceCreate,
    EvidenceOut,
    FindingIn,
    FindingOut,
    FindingVerify,
    IssueReport,
    ItemRespond,
    ItemRespondResult,
    OpeningMeeting,
    ProgrammeRow,
    ReportApproval,
    ReportOut,
    ScoreBreakdown,
    TeamAssign,
    # Web console
    AuditorRegisterRow,
    CalendarGenerate,
    DistributeReport,
    GenerationOut,
    ProgrammeApprove,
    ProgrammeAuthorise,
    ReAuditDecision,
    TemplateCreate,
    TemplateItemOut,
    TemplateOut,
    TemplateUpdate,
)

router = APIRouter(prefix="/audits", tags=["Audits"])

AUDITOR_ROLES = {"auditor"}
SAFETY_MANAGER_ROLES = {"safety_manager", "safety manager", "hse manager", "manager"}
ADMIN_ROLES = {"admin", "superadmin", "director", "isms_director"}
# Who may schedule an audit and name its auditor. The Safety Manager assigns; the
# Admin owns the calendar across sites.
ASSIGNER_ROLES = SAFETY_MANAGER_ROLES | ADMIN_ROLES
SUPERVISOR_ROLES = {"supervisor"}

# audit_scope column (migration 062) is VARCHAR(30) holding one of these codes,
# never free text.
AUDIT_SCOPES = {"inspection", "full_audit", "re_audit"}


# ══════════════════════════════════════════════════════════════════════════════
# Checklist templates
# ══════════════════════════════════════════════════════════════════════════════
#
# These used to be literal dicts here, which made "the Admin maintains the
# checklist templates every audit runs from" impossible to satisfy — there was
# nothing to maintain. They now live in `audit_templates`, backed by a versioned
# table, with the old dicts kept there as the fallback for an organisation that
# has never opened the templates screen.


# ══════════════════════════════════════════════════════════════════════════════
# Access
# ══════════════════════════════════════════════════════════════════════════════

def _role(user: CurrentUser) -> str:
    return (user.role or "").strip().lower()


def _require(user: CurrentUser, roles: set, what: str) -> None:
    if _role(user) not in roles:
        raise HTTPException(
            status_code=403, detail=f"Role '{user.role or 'unknown'}' cannot {what}"
        )


def _get(db: Session, audit_id: int, user: CurrentUser) -> Audit:
    a = db.query(Audit).filter(
        Audit.id == audit_id, Audit.organisation_id == user.org_id
    ).first()
    if not a:
        raise HTTPException(status_code=404, detail="Audit not found")
    return a


def _owned(db: Session, audit_id: int, user: CurrentUser) -> Audit:
    """The audit, and only if this auditor holds it.

    Independence is the point of the assignment step, so an auditor conducting
    someone else's audit is not a permissions nicety — it invalidates the finding.
    """
    a = _get(db, audit_id, user)
    if _role(user) in AUDITOR_ROLES and a.auditor_id not in (None, user.user_id):
        raise HTTPException(status_code=403, detail="This audit is assigned to another auditor")
    return a


def _conductor(db: Session, audit_id: int, user: CurrentUser) -> Audit:
    """Steps 3-9 belong to the auditor who holds the audit."""
    _require(user, AUDITOR_ROLES | ADMIN_ROLES, "conduct an audit")
    return _owned(db, audit_id, user)


# ══════════════════════════════════════════════════════════════════════════════
# Reading an audit
# ══════════════════════════════════════════════════════════════════════════════

def _json(value: Optional[str], fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _items(db: Session, audit_id: int) -> List[AuditChecklistItem]:
    return (
        db.query(AuditChecklistItem)
        .filter(AuditChecklistItem.audit_id == audit_id)
        .order_by(AuditChecklistItem.seq.asc(), AuditChecklistItem.id.asc())
        .all()
    )


def _findings(db: Session, audit_id: int) -> List[AuditFinding]:
    return (
        db.query(AuditFinding)
        .filter(AuditFinding.audit_id == audit_id)
        .order_by(AuditFinding.id.asc())
        .all()
    )


def _evidence(db: Session, audit_id: int) -> List[AuditEvidence]:
    return (
        db.query(AuditEvidence)
        .filter(AuditEvidence.audit_id == audit_id)
        .order_by(AuditEvidence.id.asc())
        .all()
    )


def _facts(db: Session, a: Audit) -> audit_steps.StepFacts:
    """Everything the step derivation needs, read once."""
    items = _items(db, a.id)
    findings = _findings(db, a.id)

    answered = sum(1 for i in items if audit_scoring.normalise_response(i.response) is not None)
    # Evidence is owed on anything that did not score full marks: an observation
    # or a non-conformance with no photo behind it is an assertion, not a finding.
    owed = sum(
        1 for i in items
        if audit_scoring.normalise_response(i.response) in (audit_scoring.PARTIAL, audit_scoring.NONE)
        and (i.evidence_count or 0) == 0
    )
    open_findings = sum(
        1 for f in findings
        if audit_scoring.is_non_conformance(f.classification)
        and f.status not in ("verified", "closed")
    )
    stop_work = a.status == "immediate_action"

    return audit_steps.StepFacts(
        team_assigned=bool(a.team_assigned_at),
        brief_pack_reviewed=bool(a.brief_pack_reviewed_at),
        opening_meeting_held=bool(a.opening_meeting_at),
        items_total=len(items),
        items_answered=answered,
        evidence_owed=owed,
        classified=bool(a.classified_at),
        auditee_confirmed=bool(a.auditee_confirmed_at),
        findings_locked=bool(a.findings_locked_at),
        report_issued=bool(a.report_issued_at),
        report_approved=bool(a.report_approved_at),
        open_findings=open_findings,
        # `closed_at` alone, never `status == "completed"`. Reading the status
        # here would make it impossible to reopen an audit: verify_finding clears
        # closed_at when a 30/60/90-day check fails, and the status it is about to
        # recompute would answer "still closed" and overwrite the reopen with
        # itself. Migration 064 backfilled closed_at onto the legacy completed
        # rows so nothing depends on the status fallback.
        closed=bool(a.closed_at),
        stop_work=stop_work,
    )


def _sync_status(db: Session, a: Audit) -> audit_steps.StepFacts:
    """Recompute `status` and `progress` from what the audit actually contains.

    Called after every transition. Nothing else sets status — a transition that
    forgot to would otherwise leave the audit sitting in a state its own contents
    contradict.
    """
    facts = _facts(db, a)
    a.status = audit_steps.status_for(facts)
    step = audit_steps.current(facts)
    a.progress = 100 if step is None else int(round((step.number - 1) / len(audit_steps.STEPS) * 100))
    return facts


def _finding_out(f: AuditFinding, evidence: List[AuditEvidence]) -> FindingOut:
    return FindingOut(
        id=f.id, audit_id=f.audit_id, checklist_item_id=f.checklist_item_id,
        finding_ref=f.finding_ref, section=f.section, title=f.title,
        description=f.description, clause=f.clause, classification=f.classification,
        auto_classified=bool(f.auto_classified), is_repeat=bool(f.is_repeat),
        repeat_of_audit_id=f.repeat_of_audit_id,
        corrective_action_due=f.corrective_action_due, capa_id=f.capa_id,
        status=f.status, verified_at=f.verified_at,
        verification_notes=f.verification_notes, closed_at=f.closed_at,
        evidence=[EvidenceOut.model_validate(e) for e in evidence if e.finding_id == f.id],
    )


def _to_response(db: Session, a: Audit) -> AuditResponse:
    items = _items(db, a.id)
    findings = _findings(db, a.id)
    evidence = _evidence(db, a.id)
    facts = _facts(db, a)

    # Legacy audits predate the checklist table. Their items still live in the
    # JSON blob and must keep rendering, rather than showing an empty checklist
    # because the schema moved on underneath them.
    if items:
        item_out = [
            {
                "id": i.id, "seq": i.seq, "section": i.section, "title": i.title,
                "question": i.question, "clause": i.clause,
                "is_critical": bool(i.is_critical), "critical": bool(i.is_critical),
                "response": i.response, "remarks": i.remarks,
                "classification": i.classification,
                "evidence_count": i.evidence_count or 0,
                "photo_attached": bool(i.evidence_count),
                "points_earned": i.points_earned,
                "points_possible": i.points_possible,
                "answered_at": i.answered_at,
                "gps_latitude": float(i.gps_latitude) if i.gps_latitude is not None else None,
                "gps_longitude": float(i.gps_longitude) if i.gps_longitude is not None else None,
            }
            for i in items
        ]
        # Sections are recomputed rather than read from the stored snapshot, so a
        # half-walked audit shows the score it actually has right now. The stored
        # copy is what the issued report froze, and only the report reads that.
        sections = [
            {
                "section": s.section, "score": s.score, "assessed": s.assessed,
                "points_earned": s.points_earned, "points_possible": s.points_possible,
                "below_threshold": s.below_threshold,
            }
            for s in audit_scoring.score_items(items).sections
        ]
    else:
        item_out = [dict(x) for x in _json(a.findings_json, [])]
        sections = _json(a.section_scores_json, [])

    step = audit_steps.current(facts)
    st = workflow_stages.describe("audit", a.status)

    counts: Dict[str, int] = {k: 0 for k in audit_scoring.CLASSIFICATIONS}
    for f in findings:
        if f.classification in counts:
            counts[f.classification] += 1

    return AuditResponse(
        id=a.id, organisation_id=a.organisation_id, audit_ref=a.audit_ref, title=a.title,
        checklist_type=a.checklist_type, site_id=a.site_id, site_name=a.site_name,
        department=a.department, shift=a.shift, auditor_id=a.auditor_id,
        scheduled_date=a.scheduled_date, due_date=a.due_date, status=a.status,
        priority=a.priority, progress=a.progress, compliance_score=a.compliance_score,
        findings=item_out, submitted_at=a.submitted_at,

        trigger_type=a.trigger_type,
        trigger_label=audit_programme.TRIGGERS.get(a.trigger_type or "", {}).get("label"),
        audit_scope=a.audit_scope, risk_band=a.risk_band,
        site_score=float(a.site_score) if a.site_score is not None else None,
        audit_team=_json(a.audit_team_json, []),
        auditee_manager_id=a.auditee_manager_id,
        auditee_notified_at=a.auditee_notified_at,
        notice_due_date=audit_programme.notice_due(a.scheduled_date, a.trigger_type),
        brief_pack_generated_at=a.brief_pack_generated_at,
        brief_pack_reviewed_at=a.brief_pack_reviewed_at,
        opening_meeting=_json(a.opening_meeting_json, None),
        opening_meeting_at=a.opening_meeting_at,
        closing_meeting=_json(a.closing_meeting_json, None),
        closing_meeting_at=a.closing_meeting_at,
        auditee_confirmed_at=a.auditee_confirmed_at,
        auditee_signed_name=a.auditee_signed_name,
        auditee_signature=a.auditee_signature,
        findings_locked_at=a.findings_locked_at,
        findings_locked=bool(a.findings_locked_at),
        score_band=a.score_band, overall_rating=a.overall_rating,
        section_scores=sections,
        finding_counts=counts,
        classified_findings=[_finding_out(f, evidence) for f in findings],
        auditor_signed_name=a.auditor_signed_name,
        auditor_signature=a.auditor_signature,
        report_ref=a.report_ref, report_issued_at=a.report_issued_at,
        report_approved_at=a.report_approved_at,
        report_approval_notes=a.report_approval_notes,
        re_audit_required=bool(a.re_audit_required), re_audit_reason=a.re_audit_reason,
        re_audit_due_date=a.re_audit_due_date,
        re_audit_decision=a.re_audit_decision,
        re_audit_decided_at=a.re_audit_decided_at,
        re_audit_decision_note=a.re_audit_decision_note,
        re_audit_audit_id=a.re_audit_audit_id,
        distribution_scope=a.distribution_scope,
        distributed_beyond_site_at=a.distributed_beyond_site_at,
        template_id=a.template_id,
        generated_by_programme=bool(a.generated_by_programme),
        reminder_sent_at=a.reminder_sent_at,
        closed_at=a.closed_at,
        open_finding_count=facts.open_findings,

        steps=audit_steps.describe(facts),
        current_step=step.number if step else None,
        current_step_label=step.label if step else None,

        stage=st.get("stage"), stage_number=st.get("stage_number"),
        stage_label=st.get("stage_label"),
        completed_stages=st.get("completed_stages") or [],
        total_stages=st.get("total_stages"),
    )


# ══════════════════════════════════════════════════════════════════════════════
# Reference — the rubric, the triggers, the steps. Cached by the app for offline.
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/reference")
def reference(current_user: CurrentUser = Depends(get_current_user)) -> dict:
    """Everything the app needs to explain itself with no signal.

    Audits happen in plant areas, tank farms and remote sites. The phone has to
    state the rubric, the classifications and the escalation rules the same way
    the specification does while it is offline, so they ship as data rather than
    being hard-coded into a screen that then disagrees with the backend.
    """
    return {
        "flow": audit_steps.reference(),
        "scoring": audit_scoring.rubric_reference(),
        "triggers": [{"key": k, **v} for k, v in audit_programme.TRIGGERS.items()],
        "frequency": audit_programme.frequency_reference(),
        "escalations": audit_escalation.reference(),
        "notice_days": audit_programme.NOTICE_DAYS,
        "brief_pack_days": audit_programme.BRIEF_PACK_DAYS,
        # What the scheduling form offers when the organisation has no template
        # of its own yet. An audit's checklist type decides which template seeds
        # its questions, so a free-text field could silently miss every template
        # and fall through to the generic list.
        "checklist_types": audit_templates.builtin_types(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Step 01 · the programme
# ══════════════════════════════════════════════════════════════════════════════

def _programme_row(r: AuditProgramme) -> ProgrammeRow:
    """One programme row, with the band rule's own words alongside the dates."""
    rule = audit_programme.rule_for(r.risk_band)
    today = date.today()
    return ProgrammeRow(
        site_id=r.site_id, site_name=r.site_name, risk_band=r.risk_band,
        band_label=rule.label,
        site_score=float(r.site_score) if r.site_score is not None else None,
        qualifying=rule.qualifying,
        inspection_frequency=r.inspection_frequency,
        audit_frequency=r.audit_frequency,
        next_inspection_due=r.next_inspection_due,
        next_audit_due=r.next_audit_due,
        last_audit_at=r.last_audit_at,
        re_audit_trigger=r.re_audit_trigger,
        overdue=bool(r.next_audit_due and r.next_audit_due < today),
        authorised_at=r.authorised_at,
        approved_at=r.approved_at,
        generated_at=r.generated_at,
        generated_count=r.generated_count or 0,
        scope_concerns=r.scope_concerns,
        programme_year=r.programme_year,
    )


@router.get("/programme", response_model=List[ProgrammeRow])
def get_programme(
    refresh: bool = Query(False, description="Recompute bands from the current safety score"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """The annual programme, one row per site, generated from the risk band."""
    if refresh:
        rows = audit_programme.refresh_org(db, current_user.org_id)
    else:
        rows = (
            db.query(AuditProgramme)
            .filter(AuditProgramme.organisation_id == current_user.org_id)
            .order_by(AuditProgramme.risk_band.asc(), AuditProgramme.site_name.asc())
            .all()
        )
        if not rows:
            rows = audit_programme.refresh_org(db, current_user.org_id)

    return [_programme_row(r) for r in rows]


@router.get("/escalations")
def open_escalations(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Live escalations, read-only.

    Reading a dashboard must not send mail, so this reports the conditions rather
    than firing them. The alerts themselves are raised at the transitions that
    create them.
    """
    return {
        "audits_not_conducted": audit_escalation.sweep_overdue(db, current_user.org_id),
        "definitions": audit_escalation.reference(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# List and read
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/", response_model=List[AuditResponse])
def list_audits(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Auditors see their own queue. Everyone else sees the org's audits.

    A supervisor sees the audits of the area they own — they are the auditee, and
    the two weeks' notice is meaningless if the audit is invisible to them.
    """
    role = _role(current_user)
    q = db.query(Audit).filter(Audit.organisation_id == current_user.org_id)
    if role in AUDITOR_ROLES:
        q = q.filter(Audit.auditor_id == current_user.user_id)
    elif role in SUPERVISOR_ROLES:
        emp = employee_id_for(db, current_user.user_id)
        q = q.filter(Audit.auditee_manager_id.in_([x for x in (emp, current_user.user_id) if x]))
    return [
        _to_response(db, a)
        for a in q.order_by(Audit.due_date.asc(), Audit.id.desc()).all()
    ]


# Findings that have reached a terminal state — same set the "my open
# findings" queue above already excludes, so a finding's closed-ness reads
# the same everywhere on this page.
_FINDING_CLOSED_STATUSES = ("verified", "closed")


@router.get("/kpis")
def get_audit_kpis(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Module 8 (Compliance & Audits) KPI block — client's own KPI spec
    (HSEIQ_Full_KPI_with_SampleData.xlsx, M8_Compliance_Audits):

        Audit Completion Rate %       = Audits completed / Audits planned x 100        (ISO 45001 9.2)
        Finding Closure Rate %        = Findings closed / Total findings x 100          (ISO 45001 10)
        NC Closure Rate %             = NCs closed / Total NCs x 100                    (ISO 45001 10.1)
        Regulatory Compliance Rate %  = Closed NCs / Total NCs x 100 (same proxy         (ISO 45001 6.1.3)
                                         the spec itself uses — no separate legal
                                         register exists to check against)
        Overdue Findings              = findings not yet closed whose corrective_action_due
                                         has passed — a real due-date rule, not a status
                                         string (see the CAPA fix this mirrors: a literal
                                         "Overdue" status is never written by this app's
                                         own workflow, only the original demo dataset).

    Org-scoped, all-time (matches audit_readiness.compute_audit_readiness's
    reasoning: this is the org's overall compliance posture, not windowed to
    whatever period a chart elsewhere has selected).
    """
    org_id = current_user.org_id
    today = date.today()

    audits = db.query(Audit).filter(Audit.organisation_id == org_id).all()
    audits_planned = len(audits)
    audits_completed = sum(1 for a in audits if a.closed_at or a.status == "completed")

    findings = (
        db.query(AuditFinding)
        .join(Audit, Audit.id == AuditFinding.audit_id)
        .filter(Audit.organisation_id == org_id)
        .all()
    )
    total_findings = len(findings)
    findings_closed = sum(1 for f in findings if f.status in _FINDING_CLOSED_STATUSES)
    nc_findings = [f for f in findings if audit_scoring.is_non_conformance(f.classification)]
    total_ncs = len(nc_findings)
    ncs_closed = sum(1 for f in nc_findings if f.status in _FINDING_CLOSED_STATUSES)
    overdue_findings = [
        f for f in findings
        if f.status not in _FINDING_CLOSED_STATUSES
        and f.corrective_action_due is not None
        and f.corrective_action_due < today
    ]

    def _pct(numerator: int, denominator: int):
        # None (not 0.0) when there is nothing to divide by — "no findings yet"
        # is a different fact from "0% closed", same distinction the rest of
        # this app's KPI cards already draw (e.g. Equipment's pm_compliance_pct).
        return round(numerator / denominator * 100, 1) if denominator else None

    return {
        "audit_completion_rate_pct": _pct(audits_completed, audits_planned),
        "finding_closure_rate_pct": _pct(findings_closed, total_findings),
        "nc_closure_rate_pct": _pct(ncs_closed, total_ncs),
        "regulatory_compliance_rate_pct": _pct(ncs_closed, total_ncs),
        "overdue_findings_count": len(overdue_findings),
        "detail": {
            "audits_planned": audits_planned,
            "audits_completed": audits_completed,
            "total_findings": total_findings,
            "findings_closed": findings_closed,
            "total_ncs": total_ncs,
            "ncs_closed": ncs_closed,
        },
    }


@router.get("/{audit_id}", response_model=AuditResponse)
def get_audit(
    audit_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    # _owned rather than _get: the list above already keeps an auditor from
    # browsing to someone else's queue, but without this a direct /audits/{id}
    # URL would still open it — the same independence concern _owned exists for.
    return _to_response(db, _owned(db, audit_id, current_user))


# ══════════════════════════════════════════════════════════════════════════════
# Step 01-02 · schedule and assign
# ══════════════════════════════════════════════════════════════════════════════

def _seed_checklist(db: Session, a: Audit, items: Optional[List[ChecklistItemIn]]) -> None:
    """Write the checklist as rows, highest-risk sections first.

    "Pre-populates the checklist with the highest-risk items first" — the order
    comes from the brief pack's risk weighting where there is one, so the auditor
    walks into last time's failures rather than working alphabetically towards
    them and running out of time.
    """
    if items:
        seed = [
            {
                "section": i.section, "title": i.title or "Checklist item",
                "question": i.question, "clause": i.clause,
                "is_critical": bool(i.is_critical or i.critical),
            }
            for i in items
        ]
    else:
        # From the maintained template for this audit type, falling back to a
        # built-in one. `template_id` records which version was actually used, so
        # the report can say what was asked even after the template moves on.
        template, seed = audit_templates.resolve(db, a.organisation_id, a.checklist_type)
        a.template_id = template.id if template else None
        seed = [dict(t) for t in seed]

    risk = {r["section"]: r["risk_weight"] for r in audit_brief.highest_risk_areas(db, a)}
    seed.sort(key=lambda s: -risk.get(s.get("section") or "General", 0))

    for n, s in enumerate(seed, start=1):
        db.add(AuditChecklistItem(
            organisation_id=a.organisation_id,
            audit_id=a.id,
            seq=n,
            section=s.get("section") or "General",
            title=(s.get("title") or "Checklist item")[:255],
            question=s.get("question"),
            clause=s.get("clause"),
            is_critical=bool(s.get("is_critical")),
        ))

    # Kept in step so anything still reading the blob — the web Compliance
    # section, the KPI queries — sees the same checklist the phone does.
    a.findings_json = json.dumps([
        {"id": n, "title": s.get("title"), "question": s.get("question"),
         "section": s.get("section"), "response": None, "remarks": "",
         "photo_attached": False, "critical": bool(s.get("is_critical"))}
        for n, s in enumerate(seed, start=1)
    ])


@router.post("/", response_model=AuditResponse, status_code=status.HTTP_201_CREATED)
def create_audit(
    payload: AuditCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 01. Scheduled from the programme, or raised by one of the six triggers."""
    _require(current_user, ASSIGNER_ROLES, "schedule audits")

    trigger = payload.trigger_type or "scheduled_programme"
    if trigger not in audit_programme.TRIGGERS:
        raise HTTPException(status_code=400, detail=f"Unknown trigger '{trigger}'")

    # audit_scope is a short code, not free text — the column is VARCHAR(30)
    # (migration 062). Reject anything else here rather than letting a caller's
    # sentence reach the DB and fail as an unhandled 500 on insert.
    if payload.audit_scope and payload.audit_scope not in AUDIT_SCOPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown audit_scope '{payload.audit_scope}' — use one of {sorted(AUDIT_SCOPES)}",
        )

    band_row = None
    if payload.site_id:
        band_row = audit_programme.refresh_site(
            db, current_user.org_id, payload.site_id, payload.site_name, commit=False
        )

    a = Audit(
        organisation_id=current_user.org_id,
        title=payload.title,
        checklist_type=payload.checklist_type,
        site_id=payload.site_id,
        site_name=payload.site_name,
        department=payload.department,
        shift=payload.shift,
        auditor_id=payload.auditor_id,
        scheduled_date=payload.scheduled_date,
        due_date=payload.due_date,
        status="scheduled",
        priority=payload.priority or "Med",
        progress=0,
        trigger_type=trigger,
        audit_scope=payload.audit_scope or "full_audit",
        risk_band=band_row.risk_band if band_row else None,
        site_score=band_row.site_score if band_row else None,
        auditee_manager_id=payload.auditee_manager_id,
        previous_audit_id=payload.previous_audit_id,
    )
    db.add(a)
    db.flush()
    a.audit_ref = f"AUD-{a.id:06d}"

    _seed_checklist(db, a, payload.items)

    # Assigning at creation is the common case — the Safety Manager schedules and
    # names the auditor in one action — so the notice clock starts here rather
    # than waiting for a second call that may never come.
    if payload.auditor_id:
        _record_assignment(db, a, payload.auditor_id, [], payload.auditee_manager_id, current_user)

    _sync_status(db, a)
    db.commit()
    db.refresh(a)
    return _to_response(db, a)


def _record_assignment(
    db: Session, a: Audit, lead_id: int, team_ids: List[int],
    auditee_manager_id: Optional[int], current_user: CurrentUser,
) -> None:
    a.auditor_id = lead_id
    a.audit_team_json = json.dumps(
        [{"user_id": lead_id, "role": "lead"}]
        + [{"user_id": t, "role": "member"} for t in team_ids if t != lead_id]
    )
    if auditee_manager_id:
        a.auditee_manager_id = auditee_manager_id
    a.team_assigned_at = datetime.utcnow()
    a.assigned_by = current_user.user_id

    # Two weeks' notice, "except for unannounced inspections, which carry none by
    # design" — so an unannounced trigger stamps nothing rather than stamping a
    # notice that was never given.
    if audit_programme.requires_notice(a.trigger_type) and a.auditee_manager_id:
        a.auditee_notified_at = datetime.utcnow()
        capa_notify.notify(
            db,
            org_id=a.organisation_id,
            employee_id=a.auditee_manager_id,
            title=f"Audit scheduled — {a.site_name or 'your area'}",
            message=(
                f"{a.title} is scheduled for "
                f"{a.scheduled_date.strftime('%d %b %Y') if a.scheduled_date else 'a date to be confirmed'}. "
                "Prepare records and make your team available. You will attend the opening and "
                "closing meetings."
            ),
            category="audit_scheduled",
            subject_ref=a.audit_ref,
        )

    capa_notify.notify(
        db,
        org_id=a.organisation_id,
        employee_id=employee_id_for(db, lead_id),
        title=f"Audit assigned — {a.title}",
        message=(
            f"{a.audit_ref} at {a.site_name or 'site'} is yours. Your brief pack arrives "
            f"{audit_programme.BRIEF_PACK_DAYS} days before the visit."
        ),
        category="audit_assigned",
        subject_ref=a.audit_ref,
    )


@router.post("/{audit_id}/assign-team", response_model=AuditResponse)
def assign_team(
    audit_id: int,
    payload: TeamAssign,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 02. The Safety Manager names who audits what.

    Independence is checked, not assumed: an auditor who supervises the area
    being audited cannot audit it, and the assignment is refused rather than
    warned about. A finding nobody believes is worth less than no finding.
    """
    _require(current_user, ASSIGNER_ROLES, "assign an audit team")
    a = _get(db, audit_id, current_user)

    if a.report_issued_at:
        raise HTTPException(status_code=400, detail="The report is issued — the team cannot be changed")

    auditee = payload.auditee_manager_id or a.auditee_manager_id
    if auditee and payload.lead_auditor_id == auditee:
        raise HTTPException(
            status_code=400,
            detail="The auditor cannot be the supervisor of the area being audited — "
                   "independence is what makes the finding credible",
        )

    _record_assignment(
        db, a, payload.lead_auditor_id, payload.team_member_ids, auditee, current_user
    )
    _sync_status(db, a)
    db.commit()
    db.refresh(a)
    return _to_response(db, a)


# ══════════════════════════════════════════════════════════════════════════════
# Step 03 · the brief pack
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/{audit_id}/brief-pack")
def get_brief_pack(
    audit_id: int,
    regenerate: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """The pack the auditor reads before going out.

    Generated once and stored, so the record shows what the auditor was actually
    briefed on rather than what the data looks like when someone opens it later.
    """
    a = _get(db, audit_id, current_user)

    if regenerate or not a.brief_pack_json:
        pack = audit_brief.build(db, a)
        a.brief_pack_json = json.dumps(pack, default=str)
        a.brief_pack_generated_at = datetime.utcnow()
        db.commit()
        db.refresh(a)
    else:
        pack = _json(a.brief_pack_json, {})

    return {
        "audit_id": a.id,
        "audit_ref": a.audit_ref,
        "generated_at": a.brief_pack_generated_at,
        "reviewed_at": a.brief_pack_reviewed_at,
        "due_date": audit_brief.due_date(a),
        "pack": pack,
    }


@router.post("/{audit_id}/brief-pack/reviewed", response_model=AuditResponse)
def mark_brief_reviewed(
    audit_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 03 complete — the auditor confirms they read the brief."""
    a = _conductor(db, audit_id, current_user)
    if not a.team_assigned_at:
        raise HTTPException(status_code=400, detail="No auditor has been assigned to this audit yet")
    if not a.brief_pack_json:
        pack = audit_brief.build(db, a)
        a.brief_pack_json = json.dumps(pack, default=str)
        a.brief_pack_generated_at = datetime.utcnow()
    a.brief_pack_reviewed_at = datetime.utcnow()
    _sync_status(db, a)
    db.commit()
    db.refresh(a)
    return _to_response(db, a)


# ══════════════════════════════════════════════════════════════════════════════
# Step 04 · opening meeting
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/{audit_id}/opening-meeting", response_model=AuditResponse)
def opening_meeting(
    audit_id: int,
    payload: OpeningMeeting,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 04. Scope, method and sampling, agreed jointly and captured on the spot.

    A structured record rather than a note: the whole value of the opening
    meeting is that there is no dispute afterwards about what was in or out of
    scope, and free text does not settle that argument.
    """
    a = _conductor(db, audit_id, current_user)
    if a.opening_meeting_at:
        raise HTTPException(status_code=400, detail="The opening meeting is already recorded")
    if not a.brief_pack_reviewed_at:
        raise HTTPException(
            status_code=400,
            detail="Read the brief pack before the opening meeting — it is what the scope is built from",
        )

    a.opening_meeting_json = json.dumps({
        "scope": payload.scope,
        "method": payload.method,
        "sampling_approach": payload.sampling_approach,
        "attendees": payload.attendees,
        "auditee_present": payload.auditee_present,
        "notes": payload.notes,
        "recorded_at": datetime.utcnow().isoformat(),
    })
    a.opening_meeting_at = datetime.utcnow()
    if payload.gps_latitude is not None:
        a.gps_latitude = payload.gps_latitude
        a.gps_longitude = payload.gps_longitude

    if not payload.auditee_present:
        # Not a hard stop — an audit is not blocked because a supervisor did not
        # turn up — but it is recorded, because "scope was agreed jointly" is a
        # claim the report makes and it has to be true.
        logger.info("Audit %s opening meeting held without the auditee present", a.id)

    _sync_status(db, a)
    db.commit()
    db.refresh(a)
    return _to_response(db, a)


# ══════════════════════════════════════════════════════════════════════════════
# Step 05 · field inspection, logged live
# ══════════════════════════════════════════════════════════════════════════════

def _repeat_of(db: Session, a: Audit, title: str) -> Optional[int]:
    """Which of the last two audits raised this same finding, if any."""
    prev = (
        db.query(Audit.id)
        .filter(
            Audit.organisation_id == a.organisation_id,
            Audit.id != a.id,
            Audit.submitted_at.isnot(None),
        )
    )
    prev = (
        prev.filter(Audit.site_id == a.site_id) if a.site_id
        else prev.filter(Audit.site_name == a.site_name)
    )
    prev_ids = [row[0] for row in prev.order_by(Audit.submitted_at.desc()).limit(2).all()]
    if not prev_ids:
        return None
    hit = (
        db.query(AuditFinding.audit_id)
        .filter(
            AuditFinding.audit_id.in_(prev_ids),
            AuditFinding.title == title[:255],
            AuditFinding.classification != audit_scoring.CONFORMANCE,
        )
        .first()
    )
    return hit[0] if hit else None


@router.post("/{audit_id}/items/{item_id}/respond", response_model=ItemRespondResult)
def respond_to_item(
    audit_id: int,
    item_id: int,
    payload: ItemRespond,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 05. One answer, logged where the auditor is standing.

    This is the endpoint the one-item-per-screen walk calls. It returns the
    running score so the phone can show it without recomputing the rubric, and it
    fires the critical alert here rather than at submit — "notified immediately
    if a critical item scores zero during the walk" means during the walk, while
    work can still be suspended.
    """
    a = _conductor(db, audit_id, current_user)
    if a.findings_locked_at:
        raise HTTPException(
            status_code=400,
            detail="Findings were locked at the closing meeting and can only change by formal amendment",
        )
    if not a.opening_meeting_at:
        raise HTTPException(
            status_code=400, detail="Hold the opening meeting before walking the site"
        )

    item = (
        db.query(AuditChecklistItem)
        .filter(AuditChecklistItem.id == item_id, AuditChecklistItem.audit_id == a.id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Checklist item not found")

    response = audit_scoring.normalise_response(payload.response)
    if response is None:
        raise HTTPException(
            status_code=400,
            detail=f"'{payload.response}' is not a valid response — use full, partial, none or na",
        )

    item.response = response
    item.remarks = payload.remarks
    item.points_earned = audit_scoring.POINTS.get(response)
    item.points_possible = None if response == audit_scoring.NA else audit_scoring.POINTS_POSSIBLE
    item.classification = payload.classification or audit_scoring.default_classification(
        response, bool(item.is_critical)
    )
    if payload.gps_latitude is not None:
        item.gps_latitude = payload.gps_latitude
        item.gps_longitude = payload.gps_longitude
    item.answered_at = datetime.utcnow()
    item.answered_by = current_user.user_id

    alert = None
    # A critical item scoring zero stops the job and notifies immediately. The
    # audit goes to immediate_action, which the eight-stage mapping reads as
    # RESPOND — contain first, carry on afterwards.
    if item.is_critical and response == audit_scoring.NONE:
        a.status = "immediate_action"
        audit_escalation.critical_finding(db, a, item.title)
        alert = (
            f"'{item.title}' is a critical item and scored zero. The Safety Manager and the "
            "executive have been notified. Work may be suspended before this audit finishes."
        )

    db.flush()
    items = _items(db, a.id)
    score = audit_scoring.score_items(items)
    answered = sum(1 for i in items if audit_scoring.normalise_response(i.response) is not None)

    if alert is None:
        _sync_status(db, a)
    a.compliance_score = int(round(score.score))

    is_repeat = bool(
        audit_scoring.is_non_conformance(item.classification)
        and _repeat_of(db, a, item.title)
    )

    db.commit()
    db.refresh(item)

    return ItemRespondResult(
        item={
            "id": item.id, "seq": item.seq, "section": item.section, "title": item.title,
            "question": item.question, "clause": item.clause,
            "is_critical": bool(item.is_critical), "response": item.response,
            "remarks": item.remarks, "classification": item.classification,
            "evidence_count": item.evidence_count or 0,
            "photo_attached": bool(item.evidence_count),
            "points_earned": item.points_earned, "points_possible": item.points_possible,
            "answered_at": item.answered_at,
            "gps_latitude": float(item.gps_latitude) if item.gps_latitude is not None else None,
            "gps_longitude": float(item.gps_longitude) if item.gps_longitude is not None else None,
        },
        answered=answered,
        total=len(items),
        running_score=score.score,
        running_band=score.band,
        alert=alert,
        is_repeat=is_repeat,
    )


@router.post("/{audit_id}/resume", response_model=AuditResponse)
def resume_after_stop_work(
    audit_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Contained — the walk carries on rather than starting again."""
    a = _conductor(db, audit_id, current_user)
    if a.status != "immediate_action":
        raise HTTPException(status_code=400, detail="This audit is not stopped")
    a.status = "fieldwork"
    _sync_status(db, a)
    db.commit()
    db.refresh(a)
    return _to_response(db, a)


# ══════════════════════════════════════════════════════════════════════════════
# Step 06 · evidence, linked to the line it proves
# ══════════════════════════════════════════════════════════════════════════════

# What a piece of evidence can be. Checked on write rather than left open: the
# value decides how every renderer displays it, and an unrecognised one silently
# becomes an <img> with a broken source.
EVIDENCE_KINDS = {"photo", "video", "document", "note", "scan", "interview"}

@router.post("/{audit_id}/evidence/upload")
async def upload_evidence_file(
    audit_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Store the file, return the URL to attach with POST /evidence.

    Two calls rather than one multipart endpoint because the app uploads the
    photo while the auditor is still typing the caption, and because a piece of
    evidence is not always a file — an interview answer is evidence with no
    attachment at all.
    """
    a = _conductor(db, audit_id, current_user)
    content = await file.read()
    try:
        url = media_storage.save_image(
            content, file.filename, file.content_type,
            subdir="audit", allowed_types=media_storage.EVIDENCE_CONTENT_TYPES,
        )
    except media_storage.MediaRejected as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"file_url": url, "audit_id": a.id}


@router.post("/{audit_id}/evidence", response_model=EvidenceOut, status_code=status.HTTP_201_CREATED)
def add_evidence(
    audit_id: int,
    payload: EvidenceCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 06. Attached to the specific checklist item, never to a general folder."""
    a = _conductor(db, audit_id, current_user)
    if a.findings_locked_at:
        raise HTTPException(
            status_code=400, detail="Findings are locked — evidence can no longer be added"
        )

    item = None
    if payload.checklist_item_id:
        item = (
            db.query(AuditChecklistItem)
            .filter(
                AuditChecklistItem.id == payload.checklist_item_id,
                AuditChecklistItem.audit_id == a.id,
            )
            .first()
        )
        if not item:
            raise HTTPException(status_code=404, detail="Checklist item not found on this audit")

    if payload.kind not in EVIDENCE_KINDS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown evidence kind '{payload.kind}'. "
                f"One of: {', '.join(sorted(EVIDENCE_KINDS))}"
            ),
        )
    # A recording is as much a file as a photograph is. Left out of this tuple,
    # a video could be attached with no file at all and the record would claim
    # evidence that does not exist.
    if payload.kind in ("photo", "video", "document") and not payload.file_url:
        raise HTTPException(
            status_code=400, detail=f"A {payload.kind} needs a file — upload it first"
        )

    e = AuditEvidence(
        organisation_id=a.organisation_id,
        audit_id=a.id,
        checklist_item_id=payload.checklist_item_id,
        finding_id=payload.finding_id,
        kind=payload.kind,
        file_url=payload.file_url,
        caption=payload.caption,
        scanned_ref=payload.scanned_ref,
        gps_latitude=payload.gps_latitude,
        gps_longitude=payload.gps_longitude,
        captured_at=payload.captured_at or datetime.utcnow(),
        captured_by=current_user.user_id,
        subject_employee_id=payload.subject_employee_id,
        subject_name=payload.subject_name,
        interview_prompt=payload.interview_prompt,
        competence_verified=payload.competence_verified,
    )
    db.add(e)

    if item is not None:
        item.evidence_count = (item.evidence_count or 0) + 1

    _sync_status(db, a)
    db.commit()
    db.refresh(e)
    return EvidenceOut.model_validate(e)


@router.get("/{audit_id}/evidence", response_model=List[EvidenceOut])
def list_evidence(
    audit_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    _get(db, audit_id, current_user)
    return [EvidenceOut.model_validate(e) for e in _evidence(db, audit_id)]


@router.delete("/{audit_id}/evidence/{evidence_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_evidence(
    audit_id: int,
    evidence_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    a = _conductor(db, audit_id, current_user)
    if a.findings_locked_at:
        raise HTTPException(status_code=400, detail="Findings are locked — evidence cannot be removed")
    e = (
        db.query(AuditEvidence)
        .filter(AuditEvidence.id == evidence_id, AuditEvidence.audit_id == a.id)
        .first()
    )
    if not e:
        raise HTTPException(status_code=404, detail="Evidence not found")
    if e.checklist_item_id:
        item = db.query(AuditChecklistItem).filter_by(id=e.checklist_item_id).first()
        if item and (item.evidence_count or 0) > 0:
            item.evidence_count -= 1
    db.delete(e)
    _sync_status(db, a)
    db.commit()
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Step 07 · classify and score
# ══════════════════════════════════════════════════════════════════════════════

def _apply_items(db: Session, a: Audit, items: List[ChecklistItemIn], user: CurrentUser) -> None:
    """Fold a batch of answers in — the offline catch-up path.

    A phone that worked a whole audit with no signal submits the answers together
    rather than as twenty queued PATCHes that must not be reordered.
    """
    rows = {i.id: i for i in _items(db, a.id)}
    by_seq = {i.seq: i for i in rows.values()}
    for incoming in items:
        row = rows.get(incoming.id) or by_seq.get(incoming.seq)
        if row is None:
            continue
        response = audit_scoring.normalise_response(incoming.response)
        if response is None:
            continue
        row.response = response
        row.remarks = incoming.remarks
        row.points_earned = audit_scoring.POINTS.get(response)
        row.points_possible = None if response == audit_scoring.NA else audit_scoring.POINTS_POSSIBLE
        row.classification = incoming.classification or audit_scoring.default_classification(
            response, bool(row.is_critical)
        )
        if incoming.gps_latitude is not None:
            row.gps_latitude = incoming.gps_latitude
            row.gps_longitude = incoming.gps_longitude
        row.answered_at = row.answered_at or datetime.utcnow()
        row.answered_by = row.answered_by or user.user_id


def _sync_findings(
    db: Session, a: Audit, supplied: List[FindingIn], user: CurrentUser,
) -> List[AuditFinding]:
    """Turn the classified checklist into finding rows.

    Findings the auditor supplied win over the defaults — they own the judgement.
    Two rules are not theirs to override, and are applied afterwards:

      · a critical item scoring zero is a Major NC at minimum
      · a section below 60% raises a Minor NC of its own, attributed to nobody
    """
    db.query(AuditFinding).filter(
        AuditFinding.audit_id == a.id, AuditFinding.capa_id.is_(None)
    ).delete(synchronize_session=False)
    db.flush()

    items = _items(db, a.id)
    by_id = {i.id: i for i in items}
    supplied_by_item = {f.checklist_item_id: f for f in supplied if f.checklist_item_id}
    created: List[AuditFinding] = []
    today = date.today()

    def _due(classification: str) -> Optional[date]:
        days = audit_scoring.action_due_days(classification)
        return today + timedelta(days=days) if days else None

    for item in items:
        response = audit_scoring.normalise_response(item.response)
        if response is None or response == audit_scoring.NA:
            continue

        chosen = supplied_by_item.get(item.id)
        classification = (
            chosen.classification if chosen
            else item.classification or audit_scoring.default_classification(
                response, bool(item.is_critical)
            )
        )
        if classification not in audit_scoring.CLASSIFICATIONS:
            raise HTTPException(
                status_code=400, detail=f"Unknown classification '{classification}'"
            )
        # The auditor may escalate a critical zero, never soften it.
        if item.is_critical and response == audit_scoring.NONE:
            if audit_scoring.CLASSIFICATIONS[classification]["severity"] < \
                    audit_scoring.CLASSIFICATIONS[audit_scoring.MAJOR_NC]["severity"]:
                classification = audit_scoring.MAJOR_NC

        item.classification = classification
        repeat_of = (
            _repeat_of(db, a, item.title)
            if audit_scoring.is_non_conformance(classification) else None
        )

        f = AuditFinding(
            organisation_id=a.organisation_id,
            audit_id=a.id,
            checklist_item_id=item.id,
            section=item.section,
            title=item.title[:255],
            description=(chosen.description if chosen else None) or item.remarks,
            clause=(chosen.clause if chosen else None) or item.clause,
            classification=classification,
            classified_by=user.user_id,
            auto_classified=chosen is None,
            is_repeat=bool(repeat_of),
            repeat_of_audit_id=repeat_of,
            corrective_action_due=(
                (chosen.corrective_action_due if chosen else None) or _due(classification)
            ),
            status="open" if audit_scoring.is_non_conformance(classification) else "closed",
            closed_at=None if audit_scoring.is_non_conformance(classification) else datetime.utcnow(),
            gps_latitude=item.gps_latitude,
            gps_longitude=item.gps_longitude,
        )
        db.add(f)
        created.append(f)

    # Findings raised against a section rather than a line — the auditor cannot
    # supply these and cannot suppress them.
    score = audit_scoring.score_items(items)
    for section in score.sections_below_threshold:
        f = AuditFinding(
            organisation_id=a.organisation_id,
            audit_id=a.id,
            section=section.section,
            title=f"Section '{section.section}' scored {section.score}%"[:255],
            description=(
                f"{section.section} scored {section.score}% against a "
                f"{audit_scoring.SECTION_NC_THRESHOLD}% threshold. A section falling below the "
                "threshold is a lapse in the system, not in one item."
            ),
            classification=audit_scoring.MINOR_NC,
            auto_classified=True,
            corrective_action_due=_due(audit_scoring.MINOR_NC),
            status="open",
        )
        db.add(f)
        created.append(f)

    # Anything the auditor raised that is not tied to a checklist line at all.
    for extra in supplied:
        if extra.checklist_item_id:
            continue
        if extra.classification not in audit_scoring.CLASSIFICATIONS:
            raise HTTPException(
                status_code=400, detail=f"Unknown classification '{extra.classification}'"
            )
        repeat_of = (
            _repeat_of(db, a, extra.title)
            if audit_scoring.is_non_conformance(extra.classification) else None
        )
        f = AuditFinding(
            organisation_id=a.organisation_id,
            audit_id=a.id,
            section=extra.section,
            title=extra.title[:255],
            description=extra.description,
            clause=extra.clause,
            classification=extra.classification,
            classified_by=user.user_id,
            is_repeat=bool(repeat_of),
            repeat_of_audit_id=repeat_of,
            corrective_action_due=extra.corrective_action_due or _due(extra.classification),
            status="open" if audit_scoring.is_non_conformance(extra.classification) else "closed",
            closed_at=None if audit_scoring.is_non_conformance(extra.classification) else datetime.utcnow(),
            gps_latitude=extra.gps_latitude,
            gps_longitude=extra.gps_longitude,
        )
        db.add(f)
        created.append(f)

    db.flush()
    for n, f in enumerate(created, start=1):
        f.finding_ref = f"{a.audit_ref}-F{n:02d}"
    return created


def _write_score(db: Session, a: Audit) -> audit_scoring.ScoreResult:
    items = _items(db, a.id)
    score = audit_scoring.score_items(items)
    findings = _findings(db, a.id)

    counts = {k: 0 for k in audit_scoring.CLASSIFICATIONS}
    for f in findings:
        if f.classification in counts:
            counts[f.classification] += 1

    a.points_earned = score.points_earned
    a.points_possible = score.points_possible
    a.compliance_score = int(round(score.score))
    a.score_band = score.band
    a.overall_rating = audit_scoring.overall_rating(counts)
    a.section_scores_json = json.dumps([
        {
            "section": s.section, "score": s.score, "assessed": s.assessed,
            "points_earned": s.points_earned, "points_possible": s.points_possible,
            "below_threshold": s.below_threshold,
        }
        for s in score.sections
    ])
    score.counts = counts
    score.overall_rating = a.overall_rating
    return score


@router.post("/{audit_id}/classify", response_model=AuditResponse)
def classify_findings(
    audit_id: int,
    payload: ClassifySubmit,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 07. The auditor classifies every finding; the system does the arithmetic.

    Reclassifying is allowed right up until the closing meeting locks the
    findings — the auditor is still on site and may have found the same problem
    twice or seen the evidence that changes their mind.
    """
    a = _conductor(db, audit_id, current_user)
    if a.findings_locked_at:
        raise HTTPException(
            status_code=400,
            detail="Findings were locked at the closing meeting and can only change by formal amendment",
        )
    if not a.opening_meeting_at:
        raise HTTPException(status_code=400, detail="The opening meeting has not been recorded")

    if payload.items:
        _apply_items(db, a, payload.items, current_user)
        db.flush()

    items = _items(db, a.id)
    unanswered = [i for i in items if audit_scoring.normalise_response(i.response) is None]
    if unanswered:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{len(unanswered)} checklist item(s) are unanswered — "
                f"first is '{unanswered[0].title}'. Every item needs a score or Not Applicable."
            ),
        )

    findings = _sync_findings(db, a, payload.findings, current_user)
    score = _write_score(db, a)

    if payload.shift:
        a.shift = payload.shift
    a.classified_at = datetime.utcnow()
    a.submitted_at = a.submitted_at or datetime.utcnow()
    _sync_status(db, a)
    db.flush()

    # The escalations that follow from the classifications, fired here because
    # this is the moment the classifications come into existence.
    audit_escalation.on_classification(db, a, findings)

    db.commit()
    db.refresh(a)
    logger.info(
        "Audit %s classified: %s%% (%s), %s findings, rating %s",
        a.id, score.score, score.band, len(findings), a.overall_rating,
    )
    return _to_response(db, a)


@router.get("/{audit_id}/score", response_model=ScoreBreakdown)
def get_score(
    audit_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """The live rubric breakdown — section by section, with the arithmetic shown."""
    a = _owned(db, audit_id, current_user)
    score = audit_scoring.score_items(_items(db, a.id))
    counts = {k: 0 for k in audit_scoring.CLASSIFICATIONS}
    for f in _findings(db, a.id):
        if f.classification in counts:
            counts[f.classification] += 1
    return ScoreBreakdown(
        score=score.score, band=score.band, band_label=score.band_label,
        points_earned=score.points_earned, points_possible=score.points_possible,
        assessed=score.assessed, not_applicable=score.not_applicable,
        unanswered=score.unanswered,
        overall_rating=audit_scoring.overall_rating(counts),
        explanation=score.explanation,
        sections=[
            {
                "section": s.section, "score": s.score, "assessed": s.assessed,
                "points_earned": s.points_earned, "points_possible": s.points_possible,
                "below_threshold": s.below_threshold,
            }
            for s in score.sections
        ],
        counts=counts,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Step 08 · closing meeting
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/{audit_id}/closing-meeting", response_model=AuditResponse)
def closing_meeting(
    audit_id: int,
    payload: ClosingMeeting,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 08. The supervisor confirms factual accuracy, and the findings lock.

    Both signatures are captured on the device before anyone leaves site, so the
    findings lock immediately. Refusing to confirm does not lock anything: the
    auditor goes back and corrects the factual error, which is exactly what the
    meeting is for.
    """
    a = _conductor(db, audit_id, current_user)
    if a.findings_locked_at:
        raise HTTPException(status_code=400, detail="The closing meeting is already recorded")
    if not a.classified_at:
        raise HTTPException(
            status_code=400,
            detail="Classify the findings before the closing meeting — there is nothing to present yet",
        )

    a.closing_meeting_json = json.dumps({
        "attendees": payload.attendees,
        "notes": payload.notes,
        "disputes": payload.disputes,
        "agreed_timeframes": payload.agreed_timeframes,
        "factual_accuracy_confirmed": payload.factual_accuracy_confirmed,
        "recorded_at": datetime.utcnow().isoformat(),
    })
    a.closing_meeting_at = datetime.utcnow()

    if not payload.factual_accuracy_confirmed:
        # Recorded and left open. The dispute is the point of the meeting, and
        # locking findings the auditee says are factually wrong would defeat it.
        _sync_status(db, a)
        db.commit()
        db.refresh(a)
        logger.info("Audit %s closing meeting held — factual accuracy NOT confirmed", a.id)
        return _to_response(db, a)

    if not (payload.auditee_signature and payload.auditor_signature):
        raise HTTPException(
            status_code=400,
            detail="Both signatures are required on the device before the findings lock",
        )

    # Timeframes agreed in the meeting override the default deadlines.
    for finding_id, agreed in (payload.agreed_timeframes or {}).items():
        try:
            f = db.query(AuditFinding).filter(
                AuditFinding.id == int(finding_id), AuditFinding.audit_id == a.id
            ).first()
            if f:
                f.corrective_action_due = date.fromisoformat(agreed)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400,
                detail=f"'{agreed}' is not a date for finding {finding_id} — use YYYY-MM-DD",
            )

    a.auditee_signature = payload.auditee_signature
    a.auditee_signed_name = payload.auditee_signed_name
    a.auditor_signature = payload.auditor_signature
    a.auditor_signed_name = payload.auditor_signed_name
    a.auditee_confirmed_at = datetime.utcnow()
    a.findings_locked_at = datetime.utcnow()

    _sync_status(db, a)
    db.commit()
    db.refresh(a)
    return _to_response(db, a)


# ══════════════════════════════════════════════════════════════════════════════
# Step 09 · issue the report
# ══════════════════════════════════════════════════════════════════════════════

def _raise_capas(db: Session, a: Audit, current_user: CurrentUser) -> int:
    """One corrective action per non-conformance, created when the report is signed.

    Per finding rather than per audit because each root cause gets its own
    action: an audit with six non-conformances has six things to fix, and one
    lumped action closes when the easiest is done.

    The action is left unassigned. The auditor finds the non-conformance; the
    supervisor of the area owns fixing it, and the Safety Manager decides who
    that is when the report lands.
    """
    from app.models.capa_action import CapaAction
    from app.services.capa_priority import prioritise

    now = datetime.utcnow()
    raised_by = employee_id_for(db, current_user.user_id)
    created = 0

    for f in _findings(db, a.id):
        if not audit_scoring.is_non_conformance(f.classification) or f.capa_id:
            continue

        severity = {
            audit_scoring.CRITICAL: "critical",
            audit_scoring.MAJOR_NC: "high",
            audit_scoring.MINOR_NC: "medium",
        }[f.classification]
        capa_type = {
            audit_scoring.CRITICAL: "P1",
            audit_scoring.MAJOR_NC: "P2",
            audit_scoring.MINOR_NC: "P3",
        }[f.classification]

        prio = prioritise(
            severity_potential=severity,
            # A repeat is treated as more serious than a first occurrence, and
            # systemic risk is where that lands: the control was already supposed
            # to be in place.
            systemic_risk="high" if f.is_repeat else "medium",
            capa_type=capa_type,
            created_at=now,
        )
        capa = CapaAction(
            organisation_id=a.organisation_id,
            subject_family="audit",
            subject_id=a.id,
            source="audit",
            raised_by=raised_by,
            action_type="Corrective",
            description=(
                f"{audit_scoring.CLASSIFICATIONS[f.classification]['label']}: {f.title}"
                + (f" — {f.description}" if f.description else "")
                + (" [REPEAT FINDING]" if f.is_repeat else "")
            ),
            root_cause_addressed=f.title[:255],
            # The date agreed at the closing meeting wins over the default: the
            # supervisor committed to it in front of the auditor.
            due_date=f.corrective_action_due or (prio.due_date.date() if prio.due_date else None),
            status="Open",
            severity_potential=prio.severity_potential,
            systemic_risk=prio.systemic_risk,
            priority_score=prio.priority_score,
            priority_band=prio.priority_band,
            capa_type=prio.capa_type,
            capa_type_label=prio.capa_type_label,
            target_hours=prio.target_hours,
            evidence_required=prio.evidence_required,
            priority_explanation=prio.explanation,
        )
        db.add(capa)
        db.flush()
        capa.capa_ref = f"CAPA-{capa.id:06d}"
        f.capa_id = capa.id
        f.status = "action_raised"
        created += 1

    return created


def _distribute(db: Session, a: Audit, capa_count: int) -> List[int]:
    """Who gets the report the moment it is signed.

    The supervisor because they own the actions, the Safety Manager because they
    approve it before it goes wider, the admin because they own distribution
    beyond the site.
    """
    audience: List[int] = []
    if a.auditee_manager_id:
        audience.append(a.auditee_manager_id)
    for emp in capa_notify.safety_managers(db, a.organisation_id):
        if emp not in audience:
            audience.append(emp)

    capa_notify.notify_many(
        db, audience,
        org_id=a.organisation_id,
        title=f"Audit report issued — {a.site_name or 'site'} ({a.compliance_score}%)",
        message=(
            f"{a.audit_ref}: {a.compliance_score}% ({a.score_band}), rated "
            f"{(a.overall_rating or '').replace('_', ' ')}. "
            f"{capa_count} corrective action(s) raised. "
            "The Safety Manager approves the report before wider distribution."
        ),
        category="audit_report",
        subject_ref=a.report_ref,
        type_="warning" if a.overall_rating != audit_scoring.SATISFACTORY else "info",
    )
    return audience


@router.post("/{audit_id}/issue-report", response_model=AuditResponse)
def issue_report(
    audit_id: int,
    payload: IssueReport,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 09. The report cannot be issued without the auditor's signature.

    Signing is not a formality here — it is the transition. It distributes the
    report and creates a corrective action for every non-conformance, so the two
    cannot come apart: there is no path that issues a report without raising the
    actions, and none that raises actions from a report nobody signed.
    """
    a = _conductor(db, audit_id, current_user)
    if a.report_issued_at:
        raise HTTPException(status_code=400, detail="This report has already been issued")
    if not a.findings_locked_at:
        raise HTTPException(
            status_code=400,
            detail="Findings are not locked — hold the closing meeting and get factual accuracy "
                   "confirmed before issuing the report",
        )

    a.auditor_signature = payload.auditor_signature
    a.auditor_signed_name = payload.auditor_signed_name
    a.report_ref = f"RPT-{a.id:06d}"
    a.report_issued_at = datetime.utcnow()

    capa_count = _raise_capas(db, a, current_user)
    audience = _distribute(db, a, capa_count)
    a.report_distributed_to = json.dumps(audience)

    # The site's own history now includes this audit, so the persistent-poor-
    # performance rule is evaluated here rather than before it was signed.
    escalation = audit_escalation.persistent_poor_performance(db, a)
    if escalation:
        a.re_audit_required = True
        a.re_audit_reason = escalation.detail[:160]
        a.re_audit_due_date = audit_programme.re_audit_due(a.risk_band)

    if a.site_id:
        audit_programme.refresh_site(
            db, a.organisation_id, a.site_id, a.site_name, commit=False
        )

    _sync_status(db, a)
    db.commit()
    db.refresh(a)
    logger.info(
        "Audit %s report %s issued by %s — %s corrective action(s)",
        a.id, a.report_ref, payload.auditor_signed_name, capa_count,
    )
    return _to_response(db, a)


@router.post("/{audit_id}/approve-report", response_model=AuditResponse)
def approve_report(
    audit_id: int,
    payload: ReportApproval,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """The Safety Manager reviews and approves before wider distribution."""
    _require(current_user, ASSIGNER_ROLES, "approve an audit report")
    a = _get(db, audit_id, current_user)
    if not a.report_issued_at:
        raise HTTPException(status_code=400, detail="No report has been issued yet")

    a.report_approval_notes = payload.notes
    if payload.approved:
        a.report_approved_by = current_user.user_id
        a.report_approved_at = datetime.utcnow()
    else:
        # Withdrawing approval does not unsign the report or delete the actions —
        # the findings are real and locked. It records that it must not go wider.
        a.report_approved_by = None
        a.report_approved_at = None

    db.commit()
    db.refresh(a)
    return _to_response(db, a)


@router.get("/{audit_id}/report", response_model=ReportOut)
def get_report(
    audit_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """The report, built from the data — no document is written by hand.

    Scores, findings, benchmark against last time and the standard clause
    mapping. The web console is where a long document is genuinely easier to work
    with; this is the same content the phone shows in summary.
    """
    a = _owned(db, audit_id, current_user)
    items = _items(db, a.id)
    findings = _findings(db, a.id)
    evidence = _evidence(db, a.id)
    score = audit_scoring.score_items(items)

    counts = {k: 0 for k in audit_scoring.CLASSIFICATIONS}
    for f in findings:
        if f.classification in counts:
            counts[f.classification] += 1

    previous = (
        db.query(Audit)
        .filter(
            Audit.organisation_id == a.organisation_id,
            Audit.id != a.id,
            Audit.compliance_score.isnot(None),
            (Audit.site_id == a.site_id) if a.site_id else (Audit.site_name == a.site_name),
        )
        .order_by(Audit.submitted_at.desc())
        .first()
    )

    clause_map: Dict[str, dict] = {}
    for f in findings:
        if not f.clause:
            continue
        entry = clause_map.setdefault(f.clause, {"clause": f.clause, "findings": 0, "worst": None})
        entry["findings"] += 1
        worst = entry["worst"]
        if worst is None or audit_scoring.CLASSIFICATIONS[f.classification]["severity"] > \
                audit_scoring.CLASSIFICATIONS[worst]["severity"]:
            entry["worst"] = f.classification

    return ReportOut(
        audit_id=a.id,
        report_ref=a.report_ref,
        issued_at=a.report_issued_at,
        title=a.title,
        site_name=a.site_name,
        checklist_type=a.checklist_type,
        conducted_on=a.opening_meeting_at or a.submitted_at,
        lead_auditor=a.auditor_signed_name,
        score=ScoreBreakdown(
            score=score.score, band=score.band, band_label=score.band_label,
            points_earned=score.points_earned, points_possible=score.points_possible,
            assessed=score.assessed, not_applicable=score.not_applicable,
            unanswered=score.unanswered,
            overall_rating=a.overall_rating or audit_scoring.overall_rating(counts),
            explanation=score.explanation,
            sections=_json(a.section_scores_json, []),
            counts=counts,
        ),
        findings=[_finding_out(f, evidence) for f in findings],
        benchmark={
            "previous_audit_ref": previous.audit_ref if previous else None,
            "previous_score": previous.compliance_score if previous else None,
            "previous_rating": previous.overall_rating if previous else None,
            "delta": (
                round(score.score - previous.compliance_score, 1)
                if previous and previous.compliance_score is not None else None
            ),
            "repeat_findings": sum(1 for f in findings if f.is_repeat),
        },
        clause_map=list(clause_map.values()),
        escalations=(
            [{"key": "persistent_poor_performance", "detail": a.re_audit_reason}]
            if a.re_audit_required else []
        ),
        distributed_to=_json(a.report_distributed_to, []),
        signed_by=a.auditor_signed_name,
        auditee_signed_by=a.auditee_signed_name,
        auditor_signature=a.auditor_signature,
        auditee_signature=a.auditee_signature,
        evidence=[EvidenceOut.model_validate(e) for e in evidence],
    )


# ══════════════════════════════════════════════════════════════════════════════
# Step 10 · track the findings out
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/{audit_id}/findings", response_model=List[FindingOut])
def list_findings(
    audit_id: int,
    open_only: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    _owned(db, audit_id, current_user)
    evidence = _evidence(db, audit_id)
    rows = _findings(db, audit_id)
    if open_only:
        rows = [f for f in rows if f.status not in ("verified", "closed")]
    return [_finding_out(f, evidence) for f in rows]


@router.get("/findings/open", response_model=List[FindingOut])
def my_open_findings(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Every finding still to be verified, across this auditor's audits.

    "Verifies effectiveness at 30, 60 and 90 days" needs a list that spans
    audits — chasing them one audit at a time is how the tail gets forgotten.
    """
    q = (
        db.query(AuditFinding)
        .join(Audit, Audit.id == AuditFinding.audit_id)
        .filter(
            Audit.organisation_id == current_user.org_id,
            AuditFinding.status.notin_(("verified", "closed")),
        )
    )
    if _role(current_user) in AUDITOR_ROLES:
        q = q.filter(Audit.auditor_id == current_user.user_id)
    rows = q.order_by(AuditFinding.corrective_action_due.asc()).all()
    return [_finding_out(f, []) for f in rows]


@router.post("/{audit_id}/findings/{finding_id}/verify", response_model=FindingOut)
def verify_finding(
    audit_id: int,
    finding_id: int,
    payload: FindingVerify,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 10. Confirm the finding was genuinely closed, not just marked closed.

    Answering no sends it back rather than closing it. The corrective action is
    reopened too — a finding that is still open with a completed action against
    it is the exact state this step exists to prevent.
    """
    a = _get(db, audit_id, current_user)
    _require(current_user, AUDITOR_ROLES | ASSIGNER_ROLES, "verify audit findings")
    if not a.report_issued_at:
        raise HTTPException(
            status_code=400, detail="Findings are verified after the report is issued, not before"
        )

    f = (
        db.query(AuditFinding)
        .filter(AuditFinding.id == finding_id, AuditFinding.audit_id == a.id)
        .first()
    )
    if not f:
        raise HTTPException(status_code=404, detail="Finding not found")

    if f.capa_id and payload.effective:
        from app.models.capa_action import CapaAction
        from app.services import capa_lifecycle as lc

        capa = db.query(CapaAction).filter(CapaAction.id == f.capa_id).first()
        # Terminal, not the literal "Completed". WF-04 closes an action at
        # "Closed" and never writes "Completed" — that value only exists on rows
        # raised before the lifecycle landed. Comparing against the string meant
        # a properly closed action still failed this gate, so every finding under
        # it stayed unverifiable and the audit could never reach step 10.
        if capa and not lc.is_terminal(capa.status):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Corrective action {capa.capa_ref or capa.id} is still {capa.status}. "
                    "It has to be closed before the finding can be verified."
                ),
            )

    f.verification_notes = payload.verification_notes
    f.verified_by = current_user.user_id
    if payload.gps_latitude is not None:
        f.gps_latitude = payload.gps_latitude
        f.gps_longitude = payload.gps_longitude

    if payload.effective:
        f.status = "verified"
        f.verified_at = datetime.utcnow()
        f.closed_at = datetime.utcnow()
    else:
        f.status = "open"
        f.verified_at = None
        f.closed_at = None
        # A 30/60/90-day effectiveness check that fails reopens the audit itself.
        # Leaving it closed with an open finding under it is precisely the state
        # "confirms findings were genuinely closed, not just marked closed" exists
        # to prevent — and the closed audit is what the programme reads to decide
        # the site's next audit date.
        if a.closed_at:
            a.closed_at = None
            logger.info("Audit %s reopened — finding %s was not effectively closed", a.id, f.id)
        # Recompute and flush before the action is reopened below. The CAPA
        # reopen reads `audits.status` back in raw SQL to decide whether the
        # parent needs returning to IMPROVE, and an unflushed 'completed' there
        # reads as "closed record" and fires a warning about a state we have
        # just left.
        _sync_status(db, a)
        db.flush()
        if f.capa_id:
            from app.controllers.capa_workflow import _reopen as reopen_capa_action
            from app.models.capa_action import CapaAction

            capa = db.query(CapaAction).filter(CapaAction.id == f.capa_id).first()
            if capa:
                # The full WF-04 reopen, not a status write. Setting the status
                # alone left `is_locked` at 1 on an action that had been closed,
                # so the owner sent back to redo the fix was refused by every
                # step-06 and step-07 endpoint. This also clears the independent
                # review, which attested to a control the site visit has just
                # found wanting.
                reopen_capa_action(
                    db, capa,
                    f"Finding '{f.title}' was checked on site and the fix is not holding. "
                    + (payload.verification_notes or "No further detail was given."),
                )
        capa_notify.notify_many(
            db, capa_notify.safety_managers(db, a.organisation_id),
            org_id=a.organisation_id,
            title=f"Finding not effectively closed — {f.finding_ref or f.id}",
            message=(
                f"'{f.title}' was checked on site and the fix is not holding. "
                f"{payload.verification_notes or 'No further detail was given.'}"
            ),
            category="audit_escalation",
            subject_ref=a.audit_ref,
            type_="warning",
        )

    _sync_status(db, a)
    db.commit()
    db.refresh(f)
    return _finding_out(f, _evidence(db, a.id))


@router.post("/{audit_id}/close", response_model=AuditResponse)
def close_audit(
    audit_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 10 complete. "An audit is not closed when the report is issued — it
    stays open until every corrective action it raised has been verified effective."
    """
    a = _get(db, audit_id, current_user)
    _require(current_user, AUDITOR_ROLES | ASSIGNER_ROLES, "close an audit")
    if a.closed_at or a.status == "completed":
        raise HTTPException(status_code=400, detail="This audit is already closed")
    if not a.report_issued_at:
        raise HTTPException(status_code=400, detail="The report has not been issued")

    outstanding = [
        f for f in _findings(db, a.id)
        if audit_scoring.is_non_conformance(f.classification)
        and f.status not in ("verified", "closed")
    ]
    if outstanding:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{len(outstanding)} finding(s) are not verified closed — "
                f"first is '{outstanding[0].title}'. The audit stays open until every "
                "corrective action it raised has been verified effective."
            ),
        )

    a.closed_at = datetime.utcnow()
    _sync_status(db, a)

    if a.site_id:
        audit_programme.refresh_site(db, a.organisation_id, a.site_id, a.site_name, commit=False)

    db.commit()
    db.refresh(a)
    return _to_response(db, a)


# ══════════════════════════════════════════════════════════════════════════════
# Legacy verbs — older mobile builds still call these
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/{audit_id}/start", response_model=AuditResponse)
def start_audit(
    audit_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Picks the job up. Superseded by the brief-pack review, kept for old clients."""
    a = _conductor(db, audit_id, current_user)
    if not a.team_assigned_at:
        _record_assignment(db, a, current_user.user_id, [], a.auditee_manager_id, current_user)
    _sync_status(db, a)
    db.commit()
    db.refresh(a)
    return _to_response(db, a)


@router.post("/{audit_id}/fieldwork", response_model=AuditResponse)
def begin_fieldwork(
    audit_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Legacy. Resuming after a stop-work now has its own verb — see /resume."""
    a = _conductor(db, audit_id, current_user)
    if a.status == "immediate_action":
        a.status = "fieldwork"
    _sync_status(db, a)
    db.commit()
    db.refresh(a)
    return _to_response(db, a)


@router.post("/{audit_id}/submit", response_model=AuditResponse)
def submit_audit(
    audit_id: int,
    payload: AuditSubmit,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Legacy one-shot submit, mapped onto step 07.

    An old client posting pass/fail/na gets its answers normalised onto the point
    rubric, its findings auto-classified and its score computed the new way. What
    it does not get is a report: signing is a person's act and cannot be inferred
    from a checklist arriving.
    """
    _require(current_user, AUDITOR_ROLES, "submit an audit")
    a = _owned(db, audit_id, current_user)
    if a.findings_locked_at:
        raise HTTPException(
            status_code=400,
            detail="Findings are locked — the checklist cannot be resubmitted",
        )

    # An old client never held an opening meeting, so record a minimal one rather
    # than rejecting a submitted audit for a step it does not know exists.
    if not a.brief_pack_reviewed_at:
        a.brief_pack_reviewed_at = datetime.utcnow()
    if not a.opening_meeting_at:
        a.opening_meeting_json = json.dumps({
            "scope": "Not recorded — submitted by a client that predates the opening meeting step",
            "method": "Not recorded",
            "sampling_approach": "Not recorded",
            "attendees": [],
            "auditee_present": False,
        })
        a.opening_meeting_at = datetime.utcnow()

    if payload.items:
        _apply_items(db, a, payload.items, current_user)
        db.flush()

    findings = _sync_findings(db, a, [], current_user)
    score = _write_score(db, a)
    if payload.compliance_score is not None:
        a.compliance_score = payload.compliance_score
    if payload.shift:
        a.shift = payload.shift
    a.classified_at = datetime.utcnow()
    a.submitted_at = datetime.utcnow()
    _sync_status(db, a)
    db.flush()
    audit_escalation.on_classification(db, a, findings)
    db.commit()
    db.refresh(a)
    logger.info("Audit %s submitted via the legacy verb — scored %s%%", a.id, score.score)
    return _to_response(db, a)


@router.post("/{audit_id}/verify", response_model=AuditResponse)
def verify_audit(
    audit_id: int,
    payload: AuditVerify,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Legacy whole-audit verification — verifies every open finding at once.

    Kept working, but it is the blunt version: findings are verified individually
    now, because "the fix is holding" is a claim about one control, not about six.
    """
    a = _get(db, audit_id, current_user)
    _require(current_user, AUDITOR_ROLES | ASSIGNER_ROLES, "verify an audit")

    open_findings = [
        f for f in _findings(db, a.id)
        if audit_scoring.is_non_conformance(f.classification)
        and f.status not in ("verified", "closed")
    ]
    if not open_findings:
        raise HTTPException(status_code=400, detail="This audit has no findings awaiting verification")

    now = datetime.utcnow()
    for f in open_findings:
        if payload.effective:
            f.status = "verified"
            f.verified_at = now
            f.closed_at = now
        f.verified_by = current_user.user_id
        f.verification_notes = payload.verification_notes

    _sync_status(db, a)
    db.commit()
    db.refresh(a)
    return _to_response(db, a)


# ══════════════════════════════════════════════════════════════════════════════
# WEB CONSOLE · before and after the visit
# ══════════════════════════════════════════════════════════════════════════════
#
# "Everything requiring observation, evidence or a signature happens where the
# work is. Everything requiring reading, comparison or distribution happens where
# the screen is bigger."
#
# So nothing below is part of conducting an audit. These are the Safety Manager's
# and the Admin's jobs: authorise the programme, generate the calendar, maintain
# the templates, approve and distribute the report, and own the trend review.

# A router of its own, registered ahead of the main one in main.py. Literal paths
# like /audits/templates and /audits/trends have the same shape as /audits/{id},
# and FastAPI matches in registration order — declared after it, "templates"
# would be parsed as an audit id and every one of these would 422.
web_router = APIRouter(prefix="/audits", tags=["Audits · Web console"])


# ── Checklist templates (Admin) ──────────────────────────────────────────────

def _template_out(db: Session, t) -> TemplateOut:
    using = db.query(Audit.id).filter(Audit.template_id == t.id).count()
    return TemplateOut(
        id=t.id, organisation_id=t.organisation_id, name=t.name,
        checklist_type=t.checklist_type, description=t.description,
        standard=t.standard, version=t.version, is_active=bool(t.is_active),
        is_default=bool(t.is_default),
        items=[TemplateItemOut.model_validate(i) for i in audit_templates.items_of(db, t.id)],
        audits_using=using,
    )


@web_router.get("/templates", response_model=List[TemplateOut])
def list_templates(
    include_inactive: bool = Query(False, description="Include superseded versions"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """The templates every audit runs from."""
    rows = audit_templates.list_templates(db, current_user.org_id, include_inactive)
    return [_template_out(db, t) for t in rows]


@web_router.post("/templates", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(
    payload: TemplateCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    _require(current_user, ADMIN_ROLES, "maintain checklist templates")
    if not payload.items:
        raise HTTPException(
            status_code=400,
            detail="A template with no items would hand the auditor an empty checklist",
        )
    t = audit_templates.create(
        db, current_user.org_id, current_user.user_id,
        name=payload.name, checklist_type=payload.checklist_type,
        description=payload.description, standard=payload.standard,
        is_default=payload.is_default,
        items=[i.model_dump() for i in payload.items],
    )
    db.commit()
    db.refresh(t)
    return _template_out(db, t)


@web_router.post("/templates/seed", response_model=List[TemplateOut])
def seed_templates(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Import the built-in templates so there is something to edit.

    Idempotent by checklist type — running it twice does not create two Fire
    Safety templates.
    """
    _require(current_user, ADMIN_ROLES, "maintain checklist templates")
    created = audit_templates.seed_builtins(db, current_user.org_id, current_user.user_id)
    db.commit()
    logger.info("Seeded %s built-in checklist template(s) for org %s", created, current_user.org_id)
    return [_template_out(db, t) for t in audit_templates.list_templates(db, current_user.org_id)]


@web_router.put("/templates/{template_id}", response_model=TemplateOut)
def update_template(
    template_id: int,
    payload: TemplateUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Supersede a template with a new version.

    The old one is deactivated rather than deleted. Audits already conducted
    point at it, and the report has to be able to say what was actually asked.
    """
    _require(current_user, ADMIN_ROLES, "maintain checklist templates")
    t = db.query(AuditChecklistTemplate).filter(
        AuditChecklistTemplate.id == template_id,
        AuditChecklistTemplate.organisation_id == current_user.org_id,
    ).first()
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")

    fresh = audit_templates.new_version(
        db, t, current_user.user_id,
        name=payload.name, checklist_type=payload.checklist_type,
        description=payload.description, standard=payload.standard,
        is_default=payload.is_default,
        items=[i.model_dump() for i in payload.items] if payload.items is not None else None,
    )
    db.commit()
    db.refresh(fresh)
    return _template_out(db, fresh)


@web_router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def retire_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Retire a template. It is deactivated, never deleted — see update."""
    _require(current_user, ADMIN_ROLES, "maintain checklist templates")
    t = db.query(AuditChecklistTemplate).filter(
        AuditChecklistTemplate.id == template_id,
        AuditChecklistTemplate.organisation_id == current_user.org_id,
    ).first()
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    t.is_active = False
    t.is_default = False
    t.updated_by = current_user.user_id
    db.commit()
    return None


# ── The programme · authorise, approve, generate ─────────────────────────────

@web_router.post("/programme/{site_id}/authorise", response_model=ProgrammeRow)
def authorise_programme(
    site_id: int,
    payload: ProgrammeAuthorise,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """The Safety Manager authorises the annual programme for their site.

    Computed is not the same as authorised. Nothing generates a year of work
    until a person has signed off the cadence it will be generated at.
    """
    _require(current_user, ASSIGNER_ROLES, "authorise the audit programme")
    row = db.query(AuditProgramme).filter(
        AuditProgramme.organisation_id == current_user.org_id,
        AuditProgramme.site_id == site_id,
    ).first()
    if not row:
        row = audit_programme.refresh_site(db, current_user.org_id, site_id, commit=False)

    if payload.authorised:
        row.authorised_by = current_user.user_id
        row.authorised_at = datetime.utcnow()
    else:
        # Withdrawing authorisation does not delete audits already generated —
        # they exist and may already be assigned. It stops the next generation.
        row.authorised_by = None
        row.authorised_at = None
    row.authorisation_note = payload.note
    if payload.scope_concerns is not None:
        row.scope_concerns = payload.scope_concerns

    db.commit()
    db.refresh(row)
    return _programme_row(row)


@web_router.post("/programme/approve", response_model=List[ProgrammeRow])
def approve_programme(
    payload: ProgrammeApprove,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """The Admin approves the audit calendar across all sites."""
    _require(current_user, ADMIN_ROLES, "approve the audit calendar")
    q = db.query(AuditProgramme).filter(AuditProgramme.organisation_id == current_user.org_id)
    if payload.site_ids:
        q = q.filter(AuditProgramme.site_id.in_(payload.site_ids))
    rows = q.all()

    now = datetime.utcnow()
    for r in rows:
        r.approved_by = current_user.user_id if payload.approved else None
        r.approved_at = now if payload.approved else None
    db.commit()
    return [_programme_row(r) for r in rows]


@web_router.post("/programme/generate", response_model=List[GenerationOut])
def generate_calendar(
    payload: CalendarGenerate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 01. "Builds the calendar — generates the year's events."

    Idempotent: it counts what is already booked in each window and fills only
    the gap, so running it twice produces the same calendar as running it once.
    Audits already under way are never touched.
    """
    _require(current_user, ASSIGNER_ROLES, "generate the audit calendar")

    if payload.site_id:
        row = db.query(AuditProgramme).filter(
            AuditProgramme.organisation_id == current_user.org_id,
            AuditProgramme.site_id == payload.site_id,
        ).first()
        if not row:
            raise HTTPException(status_code=404, detail="That site is not in the programme")
        results = [audit_calendar.generate_for_site(
            db, row, year=payload.year, user_id=current_user.user_id,
            checklist_type=payload.checklist_type,
            require_authorisation=payload.require_authorisation,
        )]
    else:
        results = audit_calendar.generate_for_org(
            db, current_user.org_id, year=payload.year, user_id=current_user.user_id,
            require_authorisation=payload.require_authorisation,
        )

    return [
        GenerationOut(
            site_id=r.site_id, site_name=r.site_name, risk_band=r.risk_band,
            inspections_created=r.inspections_created, audits_created=r.audits_created,
            skipped_existing=r.skipped_existing, total=r.total, reason=r.reason,
            created_ids=r.created_ids,
        )
        for r in results
    ]


@web_router.post("/programme/reminders", response_model=dict)
def send_reminders(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Send the 14-day reminders now, rather than waiting for the daily sweep."""
    _require(current_user, ASSIGNER_ROLES, "send audit reminders")
    return {"sent": audit_calendar.send_due_reminders(db, current_user.org_id)}


# ── The auditor register (Admin) ─────────────────────────────────────────────

@web_router.get("/auditors", response_model=List[AuditorRegisterRow])
def auditor_register(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """"Maintains the auditor register and their qualifications."

    Workload and average score sit next to the qualifications on purpose: naming
    an independent auditor is the Safety Manager's hard stop at step 02, and
    they cannot make that call from a list of names alone.
    """
    from sqlalchemy import text

    _require(current_user, ASSIGNER_ROLES, "view the auditor register")

    rows = db.execute(
        text(
            "SELECT u.id AS user_id, u.employee_id, u.full_name, u.email, u.is_active "
            "  FROM users u "
            "  JOIN app_roles ar ON ar.id = u.app_role_id "
            " WHERE u.organisation_id = :org AND LOWER(ar.name) = 'auditor' "
            " ORDER BY u.full_name ASC"
        ),
        {"org": current_user.org_id},
    ).mappings().all()

    out: List[AuditorRegisterRow] = []
    for r in rows:
        audits = db.query(Audit).filter(
            Audit.organisation_id == current_user.org_id,
            Audit.auditor_id == r["user_id"],
        ).all()
        scores = [a.compliance_score for a in audits if a.compliance_score is not None]
        last = max((a.submitted_at for a in audits if a.submitted_at), default=None)

        quals, expired = _qualifications_for(db, r["employee_id"])

        out.append(AuditorRegisterRow(
            user_id=r["user_id"],
            employee_id=r["employee_id"],
            name=r["full_name"],
            email=r["email"],
            is_active=bool(r["is_active"]),
            audits_assigned=len(audits),
            audits_open=sum(1 for a in audits if not a.closed_at),
            audits_closed=sum(1 for a in audits if a.closed_at),
            average_score=round(sum(scores) / len(scores), 1) if scores else None,
            last_audit_at=last,
            qualifications=quals,
            expired_qualifications=expired,
        ))
    return out


def _qualifications_for(db: Session, employee_id: Optional[int]) -> tuple[List[dict], int]:
    """The auditor's certifications, from the WF-06 competence module.

    Read through raw SQL rather than the ORM because this is a read-only join
    across a module that owns its own schema, and importing its models here would
    couple the audit controller to competence's table layout.
    """
    from sqlalchemy import text

    if not employee_id:
        return [], 0
    try:
        rows = db.execute(
            text(
                "SELECT ct.name, tr.expiry_date, tr.completion_date "
                "  FROM training_records tr "
                "  JOIN certification_types ct ON ct.id = tr.certification_type_id "
                " WHERE tr.employee_id = :emp "
                " ORDER BY tr.expiry_date DESC LIMIT 25"
            ),
            {"emp": employee_id},
        ).mappings().all()
    except Exception:
        logger.exception("Could not read qualifications for employee %s", employee_id)
        return [], 0

    today = date.today()
    quals, expired = [], 0
    for r in rows:
        is_expired = bool(r["expiry_date"] and r["expiry_date"] < today)
        if is_expired:
            expired += 1
        quals.append({
            "name": r["name"],
            "completed": r["completion_date"].isoformat() if r["completion_date"] else None,
            "expires": r["expiry_date"].isoformat() if r["expiry_date"] else None,
            "expired": is_expired,
        })
    return quals, expired


# ── Trends & oversight (step 10, web) ────────────────────────────────────────

@web_router.get("/trends")
def trends(
    window_days: int = Query(365, ge=30, le=1825),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Cross-site comparison and repeat-finding analysis.

    The question no single audit report can answer: is the same thing failing in
    more than one place? One Minor NC at one site is a lapse; the same one at six
    sites is systemic, and only this view can see it.
    """
    _require(current_user, ASSIGNER_ROLES, "view cross-site audit trends")
    return {
        "summary": audit_trends.organisation_summary(db, current_user.org_id, window_days),
        "sites": audit_trends.site_comparison(db, current_user.org_id, window_days),
        "repeat_findings": audit_trends.repeat_findings(db, current_user.org_id, window_days),
        "escalations": {
            "audits_not_conducted": audit_escalation.sweep_overdue(db, current_user.org_id),
            "definitions": audit_escalation.reference(),
        },
    }


# ── The re-audit decision (Safety Manager) ───────────────────────────────────

@web_router.post("/{audit_id}/re-audit-decision", response_model=AuditResponse)
def re_audit_decision(
    audit_id: int,
    payload: ReAuditDecision,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """"Owns the re-audit decision."

    The trigger fires on its own; what to do about it does not. Scheduling
    creates the re-audit here rather than leaving someone to remember, and
    waiving requires a reason — an unexplained waiver of a mandatory re-audit is
    the single most useful thing for a regulator to find.
    """
    _require(current_user, ASSIGNER_ROLES, "decide on a re-audit")
    a = _get(db, audit_id, current_user)

    if not a.re_audit_required:
        raise HTTPException(status_code=400, detail="No re-audit has been triggered for this audit")
    if payload.decision not in ("scheduled", "waived"):
        raise HTTPException(status_code=400, detail="Decision must be 'scheduled' or 'waived'")
    if payload.decision == "waived" and not (payload.note or "").strip():
        raise HTTPException(
            status_code=400,
            detail="Waiving a mandatory re-audit requires a reason on the record",
        )

    a.re_audit_decision = payload.decision
    a.re_audit_decided_by = current_user.user_id
    a.re_audit_decided_at = datetime.utcnow()
    a.re_audit_decision_note = payload.note

    if payload.decision == "scheduled":
        if not payload.scheduled_date:
            raise HTTPException(status_code=400, detail="A scheduled re-audit needs a date")
        scheduled = payload.scheduled_date
        template, items = audit_templates.resolve(db, a.organisation_id, a.checklist_type)
        re_audit = Audit(
            organisation_id=a.organisation_id,
            title=f"Re-audit — {a.site_name or 'site'} ({a.audit_ref})",
            checklist_type=a.checklist_type,
            site_id=a.site_id, site_name=a.site_name, department=a.department,
            auditor_id=payload.auditor_id,
            auditee_manager_id=a.auditee_manager_id,
            scheduled_date=scheduled,
            due_date=scheduled + timedelta(days=2),
            status="scheduled", priority="High", progress=0,
            trigger_type="score_threshold",
            audit_scope="re_audit",
            risk_band=a.risk_band, site_score=a.site_score,
            previous_audit_id=a.id,
            template_id=template.id if template else None,
        )
        db.add(re_audit)
        db.flush()
        re_audit.audit_ref = f"AUD-{re_audit.id:06d}"
        _seed_checklist(db, re_audit, None)
        a.re_audit_audit_id = re_audit.id

        if payload.auditor_id:
            _record_assignment(
                db, re_audit, payload.auditor_id, [], a.auditee_manager_id, current_user
            )
        _sync_status(db, re_audit)
        logger.info("Re-audit %s raised from %s", re_audit.audit_ref, a.audit_ref)
    else:
        capa_notify.notify_many(
            db, capa_notify.safety_managers(db, a.organisation_id),
            org_id=a.organisation_id,
            title=f"Re-audit waived — {a.site_name or 'site'}",
            message=(
                f"The mandatory re-audit triggered by {a.audit_ref} has been waived. "
                f"Reason: {payload.note}"
            ),
            category="audit_escalation",
            subject_ref=a.audit_ref,
            type_="warning",
        )

    db.commit()
    db.refresh(a)
    return _to_response(db, a)


# ── Distribution beyond the site (Admin) ─────────────────────────────────────

@web_router.post("/{audit_id}/distribute", response_model=AuditResponse)
def distribute_report(
    audit_id: int,
    payload: DistributeReport,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """"Owns distribution beyond the site."

    Gated on the Safety Manager's approval, not merely on the report existing:
    they review it "before wider distribution", and a report that goes wide
    before that review makes the review decorative.
    """
    _require(current_user, ADMIN_ROLES, "distribute a report beyond the site")
    a = _get(db, audit_id, current_user)

    if not a.report_issued_at:
        raise HTTPException(status_code=400, detail="No report has been issued yet")
    if not a.report_approved_at:
        raise HTTPException(
            status_code=400,
            detail="The Safety Manager reviews and approves the report before wider distribution",
        )
    if payload.scope not in ("site", "organisation", "external"):
        raise HTTPException(status_code=400, detail=f"Unknown scope '{payload.scope}'")

    recipients = list(payload.recipient_employee_ids)
    if payload.scope == "organisation" and not recipients:
        recipients = capa_notify.safety_managers(db, a.organisation_id)

    capa_notify.notify_many(
        db, recipients,
        org_id=a.organisation_id,
        title=f"Audit report — {a.site_name or 'site'} ({a.compliance_score}%)",
        message=(
            f"{a.report_ref}: {a.title}. Rated {(a.overall_rating or '').replace('_', ' ')}. "
            + (payload.note or "Shared for cross-site trend review.")
        ),
        category="audit_report",
        subject_ref=a.report_ref,
    )

    a.distribution_scope = payload.scope
    a.distributed_beyond_site_at = datetime.utcnow()
    a.distributed_beyond_site_by = current_user.user_id
    a.distribution_recipients = json.dumps(recipients)

    db.commit()
    db.refresh(a)
    logger.info("Report %s distributed to %s recipient(s) at %s scope",
                a.report_ref, len(recipients), payload.scope)
    return _to_response(db, a)
