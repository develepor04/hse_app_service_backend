"""
Role-based Incident Reporting Workflow Controller.

Flow: Worker reports → Supervisor acknowledges & investigates → Manager approves & closes.

Endpoints are role-aware: the current_user.role determines what actions are allowed.
"""
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text, func
from sqlalchemy.orm import Session

from app.config.database import SessionLocal, get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.models.incident import Incident
from app.models.capa_action import CapaAction
from app.models.employee import Employee
from app.services import capa_owners, events, statutory_reporting
from app.services.audit_log import record_audit, resolve_employee_id
from app.services.events import catalogue
from app.services.capa_priority import prioritise
from app.services.incident_severity import classify_severity
from app.services import workflow_stages
from app.services import department_scope
from app.services import supervisor_routing
from app.services import incident_next_action
from app.schemas.incident_workflow import (
    WorkerIncidentReport,
    SupervisorAcknowledge,
    SupervisorInvestigate,
    SupervisorEscalate,
    ManagerApproveInvestigation,
    ManagerVerifyEffectiveness,
    ManagerCloseIncident,
    CapaComplete,
    IncidentWorkflowResponse,
    IncidentListItem,
)

router = APIRouter(prefix="/incident-workflow", tags=["Incident Workflow"])

# ── Role constants ────────────────────────────────────────────────────────────
WORKER_ROLES = {"Worker", "Employee", "Operator", "Technician"}
SUPERVISOR_ROLES = {"Supervisor", "Site Inspector", "Safety Manager", "Safety_Manager", "Site Engineer"}
MANAGER_ROLES = {"Manager", "HSE Manager", "Admin", "Superadmin", "Safety Manager", "Safety_Manager", "Director"}
ALL_ELEVATED_ROLES = SUPERVISOR_ROLES | MANAGER_ROLES

# ── Queue membership ──────────────────────────────────────────────────────────
# Stages 04, 05, 06 and 07 all sit with the manager in one form or another.
SUPERVISOR_QUEUE_STATUSES = ["reported", "acknowledged", "under_investigation"]
MANAGER_QUEUE_STATUSES = [
    "escalated",            # 04 — needs a decision one level up
    "pending_approval",     # 04 — RCA awaiting sign-off
    "capa_open",            # 05 — visible, but the action is the assignee's
    "pending_verification", # 06 — fix done, effectiveness unconfirmed
    "approved",             # 07 — verified, awaiting the lesson and closure
]


def _get_incident(db: Session, incident_id: int, org_id: Optional[int]) -> Incident:
    """Fetch incident scoped to org."""
    q = db.query(Incident).filter(Incident.id == incident_id)
    if org_id is not None:
        q = q.filter(Incident.organisation_id == org_id)
    incident = q.first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


def _role_matches(user_role: str, allowed_roles: set) -> bool:
    """Case-insensitive role check."""
    return user_role.strip().lower() in {r.lower() for r in allowed_roles}


def _find_supervisor_for(db: Session, current_user: CurrentUser) -> Optional[int]:
    """See app.services.supervisor_routing.find_supervisor_for.

    Kept as a thin alias so this module reads the same as before. The logic
    moved out because /worker/incidents needs it too and the two must not
    drift.
    """
    return supervisor_routing.find_supervisor_for(db, current_user)


def _acting_employee_id(db: Session, current_user: CurrentUser) -> Optional[int]:
    """The employees.id behind the logged-in user.

    Resolved through `users.employee_id`, which is the real foreign key. The
    older lookups in this module match `employees.full_name ILIKE %username%`,
    which only lands when the username happens to appear inside the person's
    name — for worker01 / supervisor01 / manager01 it matches nothing. That is
    why every stage past RECORD had a timestamp but no actor: the transition was
    recorded, the person performing it was not.
    """
    row = db.execute(
        text("SELECT employee_id FROM users WHERE id = :uid"),
        {"uid": current_user.user_id},
    ).mappings().first()
    return row["employee_id"] if row and row["employee_id"] else None


def _stamp_actor(db: Session, incident: Incident, column: str, current_user: CurrentUser) -> None:
    """Record who performed a transition, if it is not already recorded.

    Only fills a null. An actor already on the incident is the person who first
    took that role, and overwriting it on every later action would turn the
    audit trail into "whoever touched it last".
    """
    if getattr(incident, column, None):
        return
    emp_id = _acting_employee_id(db, current_user)
    if emp_id:
        setattr(incident, column, emp_id)


def _has_open_capa(db: Session, incident_id: int) -> bool:
    """Is any corrective action for this incident still outstanding?"""
    return (
        db.query(CapaAction.id)
        .filter(CapaAction.incident_id == incident_id)
        .filter((CapaAction.status.is_(None)) | func.lower(CapaAction.status).notin_(["completed", "closed", "verified", "done"]))
        .first()
        is not None
    )


def _has_any_capa(db: Session, incident_id: int) -> bool:
    return db.query(CapaAction.id).filter(CapaAction.incident_id == incident_id).first() is not None


def _require_role(user_role: str, allowed_roles: set, action: str):
    """Raise 403 if role is not in allowed set."""
    if not _role_matches(user_role, allowed_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user_role}' is not authorized to {action}",
        )


# ══════════════════════════════════════════════════════════════════════════════
# WF-03 · severity classification and statutory reportability
#
# Runs on submission and again on investigation, because the treatment level is
# usually confirmed by a clinician after the worker has already filed. Both
# passes write the full decision trace, so a reclassification is auditable.
# ══════════════════════════════════════════════════════════════════════════════

def _site_jurisdiction(db: Session, incident: Incident) -> tuple:
    """(jurisdiction, region) of the site this incident happened at, via its station.

    Returns (None, None) when the incident has no station, the station has no
    site, or the site has no jurisdiction configured. The statutory service
    treats a None jurisdiction as "cannot determine" rather than defaulting to a
    regulator. `region` selects the authority within a country — emirate, state
    or member state — and is optional.
    """
    if not incident.location_station_id:
        return (None, None)
    row = db.execute(
        text(
            "SELECT s.jurisdiction, s.region FROM working_stations ws "
            "JOIN sites s ON s.id = ws.site_id WHERE ws.id = :sid"
        ),
        {"sid": incident.location_station_id},
    ).first()
    return (row[0], row[1]) if row else (None, None)


def _is_recurring(db: Session, incident: Incident) -> bool:
    """WF-03 Q5 — same event type at this site within the last 12 months.

    Scoped to the station rather than the whole organisation: "at this site" is
    what the spec asks, and an org-wide match would flag almost every slip.
    Excludes the incident itself.
    """
    if not incident.incident_type or not incident.location_station_id:
        return False

    reference = incident.incident_date_time or incident.reported_at or datetime.utcnow()
    row = db.execute(
        text(
            "SELECT COUNT(*) FROM incidents "
            " WHERE organisation_id = :org "
            "   AND incident_type = :itype "
            "   AND location_station_id = :sid "
            "   AND id <> :self_id "
            "   AND incident_date_time >= :since "
            "   AND incident_date_time <= :until"
        ),
        {
            "org": incident.organisation_id,
            "itype": incident.incident_type,
            "sid": incident.location_station_id,
            "self_id": incident.id or 0,
            "since": reference - timedelta(days=365),
            "until": reference,
        },
    ).scalar()
    return bool(row and row > 0)


def _apply_severity_and_statutory(
    db: Session,
    incident: Incident,
    *,
    treatment_level: Optional[str] = None,
    dangerous_occurrence: Optional[bool] = None,
    worst_case_fatal: Optional[bool] = None,
    days_away: Optional[int] = None,
    occupational_disease: bool = False,
    loss_of_consciousness: bool = False,
) -> None:
    """Classify the incident P1-P5 and draft any statutory obligation.

    Mutates `incident` in place. The caller commits. Any argument left as None
    falls back to what is already stored, so the investigation pass can supply
    only what it newly learned without clearing the reporter's answers.
    """
    if treatment_level is None:
        treatment_level = incident.treatment_level
    if dangerous_occurrence is None:
        dangerous_occurrence = bool(incident.dangerous_occurrence)
    if worst_case_fatal is None:
        worst_case_fatal = bool(incident.worst_case_fatal)
    if days_away is None:
        days_away = incident.days_away

    injured = str(incident.anyone_injured or "No").strip().lower() in ("yes", "true", "1")

    severity = classify_severity(
        anyone_injured=injured,
        treatment_level=treatment_level,
        days_away=days_away,
        dangerous_occurrence=bool(dangerous_occurrence),
        worst_case_fatal=bool(worst_case_fatal),
        recurring_event_type=_is_recurring(db, incident),
    )

    incident.treatment_level = treatment_level
    incident.dangerous_occurrence = int(bool(dangerous_occurrence))
    incident.worst_case_fatal = int(bool(worst_case_fatal))
    incident.severity_priority = severity.priority
    incident.severity_label = severity.label
    incident.is_hipo = int(severity.is_hipo)
    incident.is_recurring_pattern = int(severity.is_recurring)
    incident.requires_systemic_rca = int(severity.requires_systemic_rca)
    incident.severity_trace = severity.explanation
    incident.severity_classified_at = datetime.utcnow()
    incident.min_investigator = severity.min_investigator

    # Investigation SLA runs from when the incident occurred, not from when it
    # was classified — a late-classified incident does not get a longer clock.
    clock_start = incident.incident_date_time or incident.reported_at or datetime.utcnow()
    incident.investigation_due_at = (
        clock_start + timedelta(days=severity.investigation_days)
        if severity.investigation_days is not None else None
    )

    # ── Appendix A ───────────────────────────────────────────────────────────
    jurisdiction, region = _site_jurisdiction(db, incident)
    level = (treatment_level or "").strip().lower()

    result = statutory_reporting.evaluate(
        jurisdiction,
        incident_at=clock_start,
        fatality=(severity.priority == "P1" or level == "fatality"),
        injury_type=incident.injured_body_part or incident.incident_type,
        days_away=days_away,
        dangerous_occurrence=bool(dangerous_occurrence),
        hospitalised=(level == "hospitalisation"),
        hospitalised_over_24h=(level == "hospitalisation"),
        medical_treatment=(level in ("medical_treatment", "hospitalisation")),
        loss_of_consciousness=loss_of_consciousness,
        occupational_disease=occupational_disease,
        region=region,
    )

    incident.statutory_reportable = int(result.reportable)
    incident.statutory_jurisdiction = jurisdiction
    incident.statutory_summary = result.explanation[:500] if result.explanation else None
    incident.statutory_due_at = result.earliest_due_at
    most_urgent = result.most_urgent
    incident.statutory_regulator = most_urgent.regulator if most_urgent else None
    incident.statutory_obligations = [
        {
            "jurisdiction": o.jurisdiction,
            "regulator": o.regulator,
            "legal_basis": o.legal_basis,
            "event": o.event,
            "criteria": o.criteria,
            "notify_within_hours": o.notify_within_hours,
            "due_at": o.due_at.isoformat() if o.due_at else None,
            "written_due_at": o.written_due_at.isoformat() if o.written_due_at else None,
            "requires_human_authorisation": o.requires_human_authorisation,
            "encoded": o.encoded,
        }
        for o in result.obligations
    ] or None


# ══════════════════════════════════════════════════════════════════════════════
# WORKER ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/report", response_model=IncidentWorkflowResponse, status_code=status.HTTP_201_CREATED)
def worker_report_incident(
    payload: WorkerIncidentReport,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Worker submits a new incident report. Auto-notifies supervisor."""
    now = datetime.utcnow()

    hazard_in_org = db.execute(
        text("SELECT id FROM hazards WHERE id = :id AND organisation_id = :org_id"),
        {"id": payload.hazard_id, "org_id": current_user.org_id},
    ).scalar()
    if not hazard_in_org:
        raise HTTPException(status_code=404, detail="No such hazard")

    # Find the employee record for the reporter (by user email → employee match)
    # Resolved through users.employee_id, the real foreign key. This was
    # `full_name ILIKE %username%`, which only lands when the username happens
    # to appear inside the person's name — so for a login like worker01 or
    # zzztest_bw it matched nothing and the incident was written with
    # reported_by = NULL. That is why the seed carries incidents with no
    # reporter at all, and it makes department scoping impossible: with no
    # reporter there is no department to scope by.
    reporter_employee = (
        db.query(Employee)
        .filter(Employee.id == _acting_employee_id(db, current_user))
        .first()
    )

    supervisor_id = _find_supervisor_for(db, current_user)

    incident = Incident(
        organisation_id=current_user.org_id,
        report_date=now.date(),
        incident_date_time=payload.incident_date_time,
        location_station_id=payload.location_station_id,
        incident_type=payload.incident_type,
        severity=payload.severity,
        description=payload.description,
        hazard_id=payload.hazard_id,
        number_persons_involved=payload.number_persons_involved,
        reported_by=reporter_employee.id if reporter_employee else None,
        anyone_injured=payload.anyone_injured,
        injured_person_name=payload.injured_person_name,
        injured_body_part=payload.injured_body_part,
        hazard_still_present=payload.hazard_still_present,
        witnesses_json=payload.witnesses_json,
        evidence_json=payload.evidence_json,
        gps_latitude=payload.gps_latitude,
        gps_longitude=payload.gps_longitude,
        # Workflow fields
        workflow_status="reported",
        reported_at=now,
        assigned_supervisor_id=supervisor_id,
        investigation_status="Pending",
        capa_generated="No",
        days_away=payload.days_away,
    )
    db.add(incident)
    # Flush rather than commit so the incident has an id — the recurrence lookup
    # excludes the incident itself, and without an id it would match nothing.
    db.flush()

    _apply_severity_and_statutory(
        db, incident,
        treatment_level=payload.treatment_level,
        dangerous_occurrence=payload.dangerous_occurrence,
        worst_case_fatal=payload.worst_case_fatal,
        days_away=payload.days_away,
    )

    db.commit()
    db.refresh(incident)
    return incident


@router.get("/my-reports", response_model=List[IncidentListItem])
def worker_my_reports(
    skip: int = 0,
    limit: int = Query(50, le=1000),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Worker sees only their own reported incidents."""
    # Resolve the reporter's employee id via the users table (the same id that
    # POST /worker/incidents stamps as reported_by). The old name-match lookup
    # (full_name ILIKE username) never matched, so this always returned [].
    reporter_emp_id = db.execute(
        text("SELECT employee_id FROM users WHERE id = :uid"),
        {"uid": current_user.user_id},
    ).scalar()
    if not reporter_emp_id:
        return []

    rows = (
        db.query(Incident)
        .filter(Incident.organisation_id == current_user.org_id)
        .filter(Incident.reported_by == reporter_emp_id)
        .order_by(Incident.reported_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# SUPERVISOR ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/pending-review", response_model=List[IncidentListItem])
def supervisor_pending_review(
    skip: int = 0,
    limit: int = Query(50, le=1000),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Incidents awaiting a supervisor, restricted to the viewer's department.

    The docstring used to say "assigned to them" and the query did nothing of
    the sort — it returned every open incident in the organisation, so a
    supervisor in Finishing saw Maintenance's reports and vice versa.

    Now scoped by the reporter's department (department_scope), because the
    admin fixes a department on every employee when they are added. Admins and
    auditors still see the whole organisation, and an incident whose reporter
    has no department stays visible to everyone rather than falling into a gap.
    """
    _require_role(current_user.role, ALL_ELEVATED_ROLES, "view pending incidents")

    q = (
        db.query(Incident)
        .filter(Incident.organisation_id == current_user.org_id)
        .filter(Incident.workflow_status.in_(SUPERVISOR_QUEUE_STATUSES))
    )
    q = department_scope.apply_scope(q, Incident, "reported_by", db, current_user)
    rows = (
        q.order_by(Incident.reported_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return rows


@router.get("/next-actions")
def my_next_actions(
    mine_only: bool = Query(True, description="Only steps this role actually owns"),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Every open incident waiting on this user, and the exact step it needs.

    The manager dashboard's severity tiles answer "how bad is the estate"; they
    never answered "what do I do now", which is why an incident could sit in
    IMPROVE indefinitely with nobody realising a CAPA sign-off was the only
    thing holding it. This is that missing list.

    Ordered by priority then by how long the step has been outstanding, so the
    oldest P1 is at the top rather than the most recently touched record.
    """
    # Same department rule as the queues above — "what is waiting on me" must
    # not list another department's work.
    viewer_dept = None if department_scope.sees_whole_org(current_user.role) \
        else department_scope.viewer_department_id(db, current_user)
    dept_sql = department_scope.scope_sql("reported_by") if viewer_dept else ""
    params = {"org": current_user.org_id}
    if viewer_dept:
        params["viewer_dept"] = viewer_dept

    rows = db.execute(
        text(
            "SELECT id, description, incident_type, severity_priority, severity_label, "
            "       workflow_status, reported_at, created_at, investigation_due_at, "
            "       is_hipo, is_recurring_pattern, statutory_reportable, "
            "       assigned_supervisor_id, escalated_to_manager_id "
            "  FROM incidents "
            " WHERE organisation_id = :org AND workflow_status <> 'closed' "
            + dept_sql +
            " ORDER BY COALESCE(reported_at, created_at) DESC LIMIT 300"
        ),
        params,
    ).mappings().all()

    if not rows:
        return {"count": 0, "items": [], "mine_count": 0}

    # Open CAPA counts in one query, so the IMPROVE rows can name what is
    # actually outstanding instead of saying "a corrective action".
    open_capa = db.execute(
        text(
            "SELECT c.incident_id, COUNT(*) AS open_count, MIN(c.id) AS first_id, "
            "       MIN(c.description) AS first_description, MIN(c.due_date) AS first_due "
            "  FROM capa_actions c "
            " WHERE c.incident_id IN :ids AND c.status <> 'Completed' "
            " GROUP BY c.incident_id"
        ),
        {"ids": tuple(r["id"] for r in rows)},
    ).mappings().all()
    capa_by_incident = {c["incident_id"]: c for c in open_capa}

    now = datetime.utcnow()
    # See the factory's copy of this: a record the caller has already handled
    # stays in their list instead of disappearing the moment the step moves on.
    my_employee_id = db.execute(
        text("SELECT employee_id FROM users WHERE id = :uid"), {"uid": current_user.user_id}
    ).scalar()
    items = []
    mine_count = 0

    for r in rows:
        info = incident_next_action.describe(r["workflow_status"], current_user.role)
        nxt = info["next_action"]
        if not nxt:
            continue
        if info["is_mine"]:
            mine_count += 1
        elif mine_only:
            continue

        capa = capa_by_incident.get(r["id"])
        detail = nxt["detail"]
        subject = None
        if info["stage"] == workflow_stages.IMPROVE and capa:
            subject = {
                "reference": f"CAPA-{capa['first_id']:06d}",
                "description": (capa["first_description"] or "")[:120],
                "due_date": capa["first_due"].isoformat() if capa["first_due"] else None,
                "open_count": int(capa["open_count"]),
            }
            detail = (
                f"{capa['open_count']} corrective action"
                f"{'s' if capa['open_count'] != 1 else ''} still open."
            )

        due = r["investigation_due_at"]
        items.append({
            "id": r["id"],
            "reference": f"INC-{r['id']}",
            "description": (r["description"] or r["incident_type"] or "")[:140],
            "priority": r["severity_priority"],
            "severity_label": r["severity_label"],
            "workflow_status": r["workflow_status"],
            "stage": info["stage"],
            "stage_number": info["stage_number"],
            "stage_label": info["stage_label"],
            "action": nxt["action"],
            "detail": detail,
            "cta": nxt["cta"],
            "route": nxt["route"],
            "unblocks": nxt["unblocks"],
            "owner_role": nxt["owner_role"],
            "is_mine": info["is_mine"],
            "can_act": info["can_act"],
            "handled_by_me": bool(
                my_employee_id
                and (
                    r["assigned_supervisor_id"] == my_employee_id
                    or r["escalated_to_manager_id"] == my_employee_id
                )
            ),
            "subject": subject,
            "is_hipo": bool(r["is_hipo"]),
            "is_recurring": bool(r["is_recurring_pattern"]),
            "statutory_reportable": bool(r["statutory_reportable"]),
            "is_overdue": bool(due and due < now),
            "due_at": due.isoformat() if due else None,
            "waiting_since": (r["reported_at"] or r["created_at"]).isoformat()
            if (r["reported_at"] or r["created_at"]) else None,
        })

    # Overdue first, then P1..P5, then longest waiting. An unassessed incident
    # sorts last on priority but not out of the list — it still needs somebody.
    items.sort(key=lambda i: (
        not i["is_overdue"],
        i["priority"] or "P9",
        i["waiting_since"] or "9999",
    ))

    return {"count": len(items[:limit]), "items": items[:limit], "mine_count": mine_count}


@router.get("/{incident_id}/next-action")
def incident_next_step(
    incident_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Stage tracker + the one outstanding step, for the incident screen."""
    incident = _get_incident(db, incident_id, current_user.org_id)
    info = incident_next_action.describe(incident.workflow_status, current_user.role)
    return {
        "incident_id": incident.id,
        "reference": f"INC-{incident.id}",
        **info,
        "track": incident_next_action.stage_track(incident.workflow_status),
    }


@router.post("/{incident_id}/acknowledge", response_model=IncidentWorkflowResponse)
def supervisor_acknowledge(
    incident_id: int,
    payload: SupervisorAcknowledge,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Supervisor acknowledges the incident (30 min SLA target)."""
    _require_role(current_user.role, ALL_ELEVATED_ROLES, "acknowledge incidents")
    incident = _get_incident(db, incident_id, current_user.org_id)

    if incident.workflow_status not in ("reported",):
        raise HTTPException(status_code=400, detail="Incident is not in 'reported' status")

    now = datetime.utcnow()
    incident.workflow_status = "acknowledged"
    incident.acknowledged_at = now
    incident.investigation_status = "Acknowledged"
    _stamp_actor(db, incident, "assigned_supervisor_id", current_user)

    db.commit()
    db.refresh(incident)
    return incident


@router.post("/{incident_id}/start-investigation", response_model=IncidentWorkflowResponse)
def supervisor_start_investigation(
    incident_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Stage 03 -> 04. Opens the investigation before any findings exist.

    Without this, `under_investigation` was a status only a manager rejection
    could produce, so an incident jumped from RESPOND straight to the end of
    INVESTIGATE and the SLA started by `investigation_due_at` measured a window
    nothing was ever observed to be in.
    """
    _require_role(current_user.role, ALL_ELEVATED_ROLES, "investigate incidents")
    incident = _get_incident(db, incident_id, current_user.org_id)

    if incident.workflow_status not in ("acknowledged", "reported"):
        raise HTTPException(
            status_code=400,
            detail="Only an acknowledged incident can move into investigation",
        )

    now = datetime.utcnow()
    incident.workflow_status = "under_investigation"
    incident.investigation_status = "In Progress"
    if not incident.investigation_started_at:
        incident.investigation_started_at = now
    # Acknowledgement is a precondition of investigating; a supervisor who goes
    # straight here has effectively acknowledged, so record it rather than
    # leaving a hole in the audit trail.
    if not incident.acknowledged_at:
        incident.acknowledged_at = now
    _stamp_actor(db, incident, "assigned_supervisor_id", current_user)

    db.commit()
    db.refresh(incident)
    return incident


@router.post("/{incident_id}/investigate", response_model=IncidentWorkflowResponse)
def supervisor_investigate(
    incident_id: int,
    payload: SupervisorInvestigate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Supervisor submits investigation results (root cause, 5-Why, CAPA)."""
    _require_role(current_user.role, ALL_ELEVATED_ROLES, "investigate incidents")
    incident = _get_incident(db, incident_id, current_user.org_id)

    if incident.workflow_status not in ("acknowledged", "reported", "under_investigation"):
        raise HTTPException(status_code=400, detail="Incident cannot be investigated in current status")

    now = datetime.utcnow()

    # If first time investigation starts
    if not incident.investigation_started_at:
        incident.investigation_started_at = now

    incident.root_cause = payload.root_cause
    incident.five_why_analysis = payload.five_why_analysis
    incident.immediate_cause = payload.immediate_cause
    incident.immediate_actions_taken = payload.immediate_actions_taken
    incident.root_cause_category = payload.root_cause_category
    incident.severity_classification = payload.severity_classification
    incident.days_away = payload.days_away
    incident.investigation_completed_at = now
    incident.investigation_status = "Completed"
    incident.supervisor_signature = current_user.email
    _stamp_actor(db, incident, "assigned_supervisor_id", current_user)

    # Re-run the decision tree with what the investigation established. This is
    # where P1-P5 usually settles: the reporter rarely knows the treatment level
    # or whether the worst case was fatal.
    _apply_severity_and_statutory(
        db, incident,
        treatment_level=payload.treatment_level,
        dangerous_occurrence=payload.dangerous_occurrence,
        worst_case_fatal=payload.worst_case_fatal,
        days_away=payload.days_away,
        occupational_disease=payload.occupational_disease,
        loss_of_consciousness=payload.loss_of_consciousness,
    )

    # Auto-create CAPA if details provided
    if payload.capa_description:
        if payload.capa_responsible_person_id:
            owner_in_org = db.execute(
                text("SELECT id FROM employees WHERE id = :id AND organisation_id = :org_id"),
                {"id": payload.capa_responsible_person_id, "org_id": current_user.org_id},
            ).scalar()
            if not owner_in_org:
                raise HTTPException(status_code=404, detail="No such employee")
        # WF-04: the CAPA inherits its type from the incident's P1-P5 severity,
        # which sets the deadline. The matrix score needs severity potential and
        # systemic risk, which the supervisor supplies — without them the CAPA
        # still gets a type and due date, just no priority band.
        prio = prioritise(
            severity_potential=payload.capa_severity_potential,
            systemic_risk=payload.capa_systemic_risk,
            capa_type=payload.capa_type,
            incident_priority=incident.severity_priority,
            created_at=now,
        )
        capa = CapaAction(
            organisation_id=current_user.org_id,
            incident_id=incident.id,
            # Migration 056 backfilled the polymorphic link once but this path
            # never populated it, so every action raised since then read
            # subject_family NULL and was invisible to the shared CAPA lifecycle.
            subject_family="incident",
            subject_id=incident.id,
            source="incident",
            raised_by=_acting_employee_id(db, current_user),
            action_type="Corrective",
            description=payload.capa_description,
            root_cause_addressed=payload.root_cause,
            responsible_person_id=payload.capa_responsible_person_id,
            # An explicitly supplied due date wins — a supervisor who sets one
            # has a reason. Otherwise WF-04's rule computes it.
            due_date=payload.capa_due_date or (prio.due_date.date() if prio.due_date else None),
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
        if capa.responsible_person_id:
            capa.assigned_by = capa.raised_by
            capa.assigned_at = now
        incident.capa_generated = "Yes"

        # Send notification
        try:
            from app.models.employee import Employee
            from app.models.notification import Notification
            # NOT `from datetime import datetime` here. This block is nested
            # inside supervisor_investigate, and a local import binds the name
            # for the *whole* function — which made the `now = datetime.utcnow()`
            # at the top of the function raise UnboundLocalError before this
            # line ever ran, so submitting an investigation failed outright.
            # The module already imports datetime at the top.

            emp_name = "Employee"
            if capa.responsible_person_id:
                emp = db.query(Employee).filter(Employee.id == capa.responsible_person_id).first()
                if emp:
                    emp_name = emp.full_name or f"EMP-{capa.responsible_person_id}"

            # Addressed to the owner, not broadcast. This read target_type="all",
            # so a notification naming one person was delivered to the whole
            # organisation and the person who had to act got no more signal than
            # anyone else. See migration 061.
            notif = Notification(
                organisation_id=current_user.org_id,
                title=f"{capa.capa_ref} assigned to you",
                message=(
                    f"A new corrective action has been assigned to {emp_name}: "
                    f"{capa.description}\nDue {capa.due_date or 'not set'}."
                ),
                type="info",
                target_type="specific" if capa.responsible_person_id else "all",
                target_employee_id=capa.responsible_person_id,
                category="capa_assigned",
                subject_ref=capa.capa_ref,
                status="sent",
                sent_at=datetime.utcnow()
            )
            db.add(notif)
        except Exception as e:
            logger.error("Failed to create assignment notification: %s", e)

    # Handle escalation
    if payload.escalate:
        incident.workflow_status = "escalated"
        incident.escalation_reason = payload.escalation_reason
        incident.escalated_at = now
        # Find manager to escalate to
        if not incident.escalated_to_manager_id:
            from app.models.role import Role
            mgr = (
                db.query(Employee)
                .join(Role, Employee.role_id == Role.id)
                .filter(Employee.organisation_id == current_user.org_id)
                .filter(Role.role_name.in_(["Manager", "HSE Manager"]))
                .filter(Employee.active_status == "Active")
                .first()
            )
            if mgr:
                incident.escalated_to_manager_id = mgr.id
    else:
        incident.workflow_status = "pending_approval"

    db.commit()
    db.refresh(incident)
    return incident


@router.post("/{incident_id}/escalate", response_model=IncidentWorkflowResponse)
def supervisor_escalate(
    incident_id: int,
    payload: SupervisorEscalate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Supervisor explicitly escalates incident to manager."""
    _require_role(current_user.role, ALL_ELEVATED_ROLES, "escalate incidents")
    incident = _get_incident(db, incident_id, current_user.org_id)

    if incident.workflow_status in ("closed",):
        raise HTTPException(status_code=400, detail="Cannot escalate a closed incident")

    from_status = incident.workflow_status
    now = datetime.utcnow()
    incident.workflow_status = "escalated"
    incident.escalation_reason = payload.escalation_reason
    incident.escalated_at = now
    _stamp_actor(db, incident, "assigned_supervisor_id", current_user)

    if payload.escalated_to_manager_id:
        manager_in_org = db.execute(
            text("SELECT id FROM employees WHERE id = :id AND organisation_id = :org_id"),
            {"id": payload.escalated_to_manager_id, "org_id": current_user.org_id},
        ).scalar()
        if not manager_in_org:
            raise HTTPException(status_code=404, detail="No such employee")
        incident.escalated_to_manager_id = payload.escalated_to_manager_id
    elif not incident.escalated_to_manager_id:
        from app.models.role import Role
        mgr = (
            db.query(Employee)
            .join(Role, Employee.role_id == Role.id)
            .filter(Employee.organisation_id == current_user.org_id)
            .filter(Role.role_name.in_(["Manager", "HSE Manager"]))
            .filter(Employee.active_status == "Active")
            .first()
        )
        if mgr:
            incident.escalated_to_manager_id = mgr.id

    record_audit(db, current_user.org_id, resolve_employee_id(db, current_user.user_id), "escalate", "incident", incident.id, from_status, "escalated")
    db.commit()
    db.refresh(incident)
    return incident


# ══════════════════════════════════════════════════════════════════════════════
# MANAGER ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/manager-queue", response_model=List[IncidentListItem])
def manager_queue(
    skip: int = 0,
    limit: int = Query(50, le=1000),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Every incident waiting on a manager decision, at whichever stage.

    Three of these need an action from the manager — approve the RCA (04),
    verify the fix (06), close it out (07) — and `capa_open` is here so an
    incident does not vanish from the manager's view for the length of a CAPA
    that may run 90 days.
    """
    _require_role(current_user.role, MANAGER_ROLES, "view manager queue")

    q = (
        db.query(Incident)
        .filter(Incident.organisation_id == current_user.org_id)
        .filter(Incident.workflow_status.in_(MANAGER_QUEUE_STATUSES))
    )
    # Same department rule as the supervisor queue: the manager of a department
    # decides on that department's incidents. Admins and auditors are exempt.
    q = department_scope.apply_scope(q, Incident, "reported_by", db, current_user)
    rows = (
        # MySQL has no NULLS LAST; a DESC sort already orders NULLs last there.
        q.order_by(Incident.escalated_at.desc(), Incident.reported_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return rows


@router.post("/{incident_id}/approve-investigation", response_model=IncidentWorkflowResponse)
def manager_approve_investigation(
    incident_id: int,
    payload: ManagerApproveInvestigation,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Manager approves or rejects the investigation."""
    _require_role(current_user.role, MANAGER_ROLES, "approve investigations")
    incident = _get_incident(db, incident_id, current_user.org_id)

    if incident.workflow_status not in ("pending_approval", "escalated"):
        raise HTTPException(status_code=400, detail="Incident is not awaiting manager approval")

    if payload.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="Decision must be 'approved' or 'rejected'")

    now = datetime.utcnow()
    # Whether approved or sent back, a manager made the call — record which one.
    _stamp_actor(db, incident, "escalated_to_manager_id", current_user)

    if payload.decision == "approved":
        incident.approved_at = now
        incident.investigation_status = "Approved"
        # Approving the RCA ends stage 04. Where it goes next depends on whether
        # there is anything to improve: an incident with outstanding corrective
        # actions belongs in IMPROVE until they are done, one whose actions are
        # already complete needs its effectiveness confirmed, and one that
        # produced no action at all has nothing to verify and goes to LEARN.
        if _has_open_capa(db, incident.id):
            incident.workflow_status = "capa_open"
        elif _has_any_capa(db, incident.id):
            incident.workflow_status = "pending_verification"
        else:
            incident.workflow_status = "approved"
    else:
        # Send back to supervisor for re-investigation
        incident.workflow_status = "under_investigation"
        incident.investigation_status = "Rejected - Redo"
        incident.investigation_completed_at = None

    db.commit()
    db.refresh(incident)
    return incident


@router.post("/{incident_id}/verify-effectiveness", response_model=IncidentWorkflowResponse)
def manager_verify_effectiveness(
    incident_id: int,
    payload: ManagerVerifyEffectiveness,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Stage 06 VERIFY — confirm the corrective action actually worked.

    A negative verification is not a rejection of the paperwork; it means the
    hazard is still live. The incident goes back to IMPROVE and its CAPAs are
    reopened, because closing an incident whose fix did not hold is the failure
    mode this stage exists to prevent.
    """
    _require_role(current_user.role, MANAGER_ROLES, "verify corrective actions")
    incident = _get_incident(db, incident_id, current_user.org_id)

    if incident.workflow_status not in ("pending_verification", "capa_open"):
        raise HTTPException(
            status_code=400, detail="Incident has no corrective action awaiting verification"
        )
    if incident.workflow_status == "capa_open" and _has_open_capa(db, incident.id):
        raise HTTPException(
            status_code=400,
            detail="Corrective actions are still open — they must be completed before verification",
        )

    now = datetime.utcnow()
    emp_id = db.execute(
        text("SELECT employee_id FROM users WHERE id = :uid"), {"uid": current_user.user_id}
    ).scalar()

    if payload.effective:
        incident.workflow_status = "approved"
        incident.capa_verified_by = emp_id
        incident.capa_verified_at = now
        incident.capa_verification_notes = payload.verification_notes
    else:
        incident.workflow_status = "capa_open"
        incident.capa_verified_by = None
        incident.capa_verified_at = None
        incident.capa_verification_notes = payload.verification_notes
        incident.capa_verification_failures = (incident.capa_verification_failures or 0) + 1
        # Reopen the actions. A CAPA that did not work is not a completed CAPA,
        # and leaving it closed would let the incident walk straight back to
        # verification with nothing having changed.
        db.query(CapaAction).filter(
            CapaAction.incident_id == incident.id,
            func.lower(CapaAction.status).in_(["completed", "closed", "verified", "done"]),
        ).update({"status": "Open"}, synchronize_session=False)

    db.commit()
    db.refresh(incident)
    return incident


@router.post("/{incident_id}/close", response_model=IncidentWorkflowResponse)
def manager_close_incident(
    incident_id: int,
    payload: ManagerCloseIncident,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Manager formally closes the incident."""
    _require_role(current_user.role, MANAGER_ROLES, "close incidents")
    incident = _get_incident(db, incident_id, current_user.org_id)

    if incident.workflow_status == "closed":
        raise HTTPException(status_code=400, detail="Incident is already closed")

    # Stage 08 is the end of the ring, not a shortcut across it. Closure now
    # requires the incident to have reached LEARN, which means its RCA was
    # approved, its corrective actions completed and their effectiveness
    # verified. Closing straight out of capa_open was how an incident could be
    # signed off with its fix still outstanding.
    if incident.workflow_status != "approved":
        stage = workflow_stages.describe("incident", incident.workflow_status)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Incident is at stage {stage.get('stage_number')} "
                f"{stage.get('stage_label') or incident.workflow_status} and cannot be closed yet. "
                "It must clear investigation approval, corrective action and effectiveness "
                "verification first."
            ),
        )

    now = datetime.utcnow()
    incident.workflow_status = "closed"
    incident.closed_at = now
    incident.closure_notes = payload.closure_notes
    incident.regulatory_notified = payload.regulatory_notified
    incident.lessons_learned = payload.lessons_learned
    incident.communicated_to_teams = payload.communicated_to_teams
    incident.manager_signature = current_user.email
    incident.investigation_status = "Closed"
    _stamp_actor(db, incident, "escalated_to_manager_id", current_user)

    # ── Stage 08 CLOSE · "update everything" ─────────────────────────────────
    # The event goes in this transaction (outbox): if the close rolls back, so
    # does the intent to cascade. Handlers run after the commit, on their own
    # sessions — a failing downstream consumer must never undo the closure.
    event_id = events.publish(
        db, catalogue.INCIDENT_CLOSED,
        organisation_id=incident.organisation_id,
        subject_family="incident", subject_id=incident.id,
        user_id=current_user.user_id,
        payload={
            "reference": f"INC-{incident.id}",
            "hazard_id": incident.hazard_id,
            "location_station_id": incident.location_station_id,
            "priority": incident.severity_priority,
            "is_hipo": bool(incident.is_hipo),
            "root_cause": incident.root_cause,
            "root_cause_category": incident.root_cause_category,
            "lessons_learned": incident.lessons_learned,
            "involved_employee_id": incident.reported_by,
            "reported_by": incident.reported_by,
        },
    )

    db.commit()
    db.refresh(incident)

    events.dispatch(SessionLocal, event_id)
    return incident


# ══════════════════════════════════════════════════════════════════════════════
# APPENDIX A · statutory notification queue
#
# The platform drafts the obligation. A human authorises it. Appendix A is
# explicit: "All regulatory submissions remain subject to human review and
# authorisation." Nothing here submits to a regulator — recording the
# authorisation is the whole job.
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/statutory/queue")
def statutory_queue(
    include_authorised: bool = Query(False, description="Include already-authorised notifications"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Incidents with an outstanding statutory notification, most urgent first."""
    _require_role(current_user.role, ALL_ELEVATED_ROLES, "view the statutory notification queue")

    q = (
        db.query(Incident)
        .filter(Incident.organisation_id == current_user.org_id)
        .filter(Incident.statutory_reportable == 1)
    )
    if not include_authorised:
        q = q.filter(Incident.statutory_authorised_at.is_(None))

    rows = q.order_by(Incident.statutory_due_at.asc()).limit(200).all()
    now = datetime.utcnow()

    return [
        {
            "id": r.id,
            "reference": f"INC-{r.id}",
            "incident_type": r.incident_type,
            "severity_priority": r.severity_priority,
            "severity_label": r.severity_label,
            "is_hipo": bool(r.is_hipo),
            "jurisdiction": r.statutory_jurisdiction,
            "regulator": r.statutory_regulator,
            "summary": r.statutory_summary,
            "obligations": r.statutory_obligations,
            "due_at": r.statutory_due_at.isoformat() if r.statutory_due_at else None,
            "overdue": bool(r.statutory_due_at and r.statutory_due_at < now and not r.statutory_authorised_at),
            "authorised_at": r.statutory_authorised_at.isoformat() if r.statutory_authorised_at else None,
            "reference_number": r.statutory_reference,
        }
        for r in rows
    ]


@router.post("/{incident_id}/statutory/authorise")
def authorise_statutory_notification(
    incident_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Record that a manager authorised the statutory notification.

    `statutory_reference` is the regulator's own reference (an HSE RIDDOR case
    number, an OSHA report id) and is captured so the audit trail links our
    record to theirs.
    """
    _require_role(current_user.role, MANAGER_ROLES, "authorise statutory notifications")
    incident = _get_incident(db, incident_id, current_user.org_id)

    if not incident.statutory_reportable:
        raise HTTPException(
            status_code=400,
            detail="This incident has no statutory notification to authorise",
        )
    if incident.statutory_authorised_at:
        raise HTTPException(status_code=400, detail="Statutory notification already authorised")

    emp_id = db.execute(
        text("SELECT employee_id FROM users WHERE id = :uid"), {"uid": current_user.user_id}
    ).scalar()

    incident.statutory_authorised_by = emp_id
    incident.statutory_authorised_at = datetime.utcnow()
    incident.statutory_reference = (payload or {}).get("statutory_reference")
    # Keeps the manager-facing closure flag consistent with the audit record.
    incident.regulatory_notified = "Yes"

    db.commit()
    db.refresh(incident)
    return {
        "success": True,
        "data": {
            "id": incident.id,
            "statutory_authorised_at": incident.statutory_authorised_at.isoformat(),
            "statutory_authorised_by": incident.statutory_authorised_by,
            "statutory_reference": incident.statutory_reference,
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# SHARED / OVERVIEW ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/all", response_model=List[IncidentListItem])
def list_all_workflow_incidents(
    skip: int = 0,
    limit: int = Query(100, le=1000),
    workflow_status: Optional[str] = Query(None, description="Filter by status"),
    severity: Optional[str] = Query(None),
    incident_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List all incidents for the org with optional filters. Available to all authenticated users."""
    q = db.query(Incident).filter(Incident.organisation_id == current_user.org_id)

    if workflow_status:
        q = q.filter(Incident.workflow_status == workflow_status)
    if severity:
        q = q.filter(Incident.severity == severity)
    if incident_type:
        q = q.filter(Incident.incident_type == incident_type)

    rows = q.order_by(Incident.reported_at.desc(), Incident.created_at.desc()).offset(skip).limit(limit).all()
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# AUDITOR — close-out review
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/audit-list")
def auditor_closeout_list(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Closed incidents the auditor reviews the close-out of. Returns the
    completeness signals the spec asks the auditor to check rather than making
    them open each record.

    Closed only. This used to include "approved" and "investigated", which was
    harmless while nothing set them — but "approved" is now a live pre-closure
    status (stage 07 LEARN), and a close-out review of an incident that has not
    been closed is reviewing something that does not exist yet. The auditor sits
    outside the workflow: they look at finished work.
    """
    rows = (
        db.query(Incident)
        .filter(
            Incident.organisation_id == current_user.org_id,
            Incident.workflow_status == "closed",
        )
        .order_by(Incident.closed_at.desc(), Incident.id.desc())
        .limit(100)
        .all()
    )

    return [
        {
            "id": r.id,
            "reference": f"INC-{r.id}",
            "incident_type": r.incident_type,
            "severity": r.severity,
            "workflow_status": r.workflow_status,
            # Completeness checks the auditor signs against
            "investigation_status": r.investigation_status,
            "has_five_why": bool(r.five_why_analysis),
            "closure_notes": r.closure_notes,
            "lessons_learned": r.lessons_learned,
            "communicated_to_teams": r.communicated_to_teams,
            "manager_signature": r.manager_signature,
            "closed_at": r.closed_at.isoformat() if r.closed_at else None,
            "auditor_verified_at": r.auditor_verified_at.isoformat() if r.auditor_verified_at else None,
            "verification_notes": r.verification_notes,
        }
        for r in rows
    ]


@router.post("/{incident_id}/verify")
def auditor_verify_closeout(
    incident_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Auditor sign-off note on an incident close-out."""
    incident = _get_incident(db, incident_id, current_user.org_id)

    emp_id = db.execute(
        text("SELECT employee_id FROM users WHERE id = :uid"), {"uid": current_user.user_id}
    ).scalar()

    incident.auditor_verified_by = emp_id
    incident.auditor_verified_at = datetime.now()
    incident.verification_notes = (payload or {}).get("verification_notes")
    db.commit()
    db.refresh(incident)

    return {
        "success": True,
        "data": {
            "id": incident.id,
            "auditor_verified_at": incident.auditor_verified_at.isoformat(),
            "verification_notes": incident.verification_notes,
        },
    }


@router.get("/{incident_id}", response_model=IncidentWorkflowResponse)
def get_incident_detail(
    incident_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get full incident detail with all workflow fields.

    The record stores `location_station_id`, `hazard_id` and `reported_by` as
    foreign keys. The supervisor reviewing the report needs the names — "Heavy
    Assembly Station 1", not "84" — so they are resolved here rather than making
    every client fetch three lookup tables and join them itself.
    """
    incident = _get_incident(db, incident_id, current_user.org_id)

    def _scalar(sql: str, key: Optional[int]) -> Optional[str]:
        if not key:
            return None
        return db.execute(text(sql), {"id": key}).scalar()

    # Attached, not stored: these are display labels derived on read, so they
    # cannot go stale against the tables they came from.
    incident.location_station_name = _scalar(
        "SELECT station_name FROM working_stations WHERE id = :id", incident.location_station_id
    )
    incident.hazard_name = _scalar(
        "SELECT hazard_name FROM hazards WHERE id = :id", incident.hazard_id
    )
    incident.reported_by_name = _scalar(
        "SELECT full_name FROM employees WHERE id = :id", incident.reported_by
    )
    incident.supervisor_name = _scalar(
        "SELECT full_name FROM employees WHERE id = :id", incident.assigned_supervisor_id
    )

    # The corrective actions the supervisor raised. The manager is approving an
    # investigation whose whole point is the CAPA, so it has to travel with the
    # record — `capa_generated` was a bare Yes/No, which told the approver that
    # an action exists but not what it is, who owns it or when it is due.
    incident.capa_actions = [
        {
            "id": r.id,
            "description": r.description,
            "action_type": r.action_type,
            "root_cause_addressed": r.root_cause_addressed,
            "responsible_person_id": r.responsible_person_id,
            "responsible_person_name": _scalar(
                "SELECT full_name FROM employees WHERE id = :id", r.responsible_person_id
            ),
            "due_date": r.due_date.isoformat() if r.due_date else None,
            "status": r.status,
            "priority_band": r.priority_band,
            "capa_type_label": r.capa_type_label,
            "evidence_required": r.evidence_required,
            "effectiveness_rating": r.effectiveness_rating,
        }
        for r in db.query(CapaAction)
        .filter(CapaAction.incident_id == incident.id)
        .order_by(CapaAction.id.desc())
        .all()
    ]
    return incident


@router.get("/stats/summary")
def workflow_stats(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Quick summary counts per workflow status for dashboard widgets."""
    from sqlalchemy import func

    org_id = current_user.org_id
    rows = (
        db.query(Incident.workflow_status, func.count(Incident.id))
        .filter(Incident.organisation_id == org_id)
        .group_by(Incident.workflow_status)
        .all()
    )
    counts = {status: count for status, count in rows}
    return {
        "reported": counts.get("reported", 0),
        "acknowledged": counts.get("acknowledged", 0),
        "under_investigation": counts.get("under_investigation", 0),
        "escalated": counts.get("escalated", 0),
        "pending_approval": counts.get("pending_approval", 0),
        "closed": counts.get("closed", 0),
        "total": sum(counts.values()),
    }


# ══════════════════════════════════════════════════════════════════════════════
# CAPA — mobile completion
# CAPA actions are auto-created above when a supervisor's investigation includes
# a capa_description, but nothing else in the app ever moves them past "Open".
# The website's CAPA Closure Rate can only change through this endpoint.
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/capa/assignable-owners")
def capa_assignable_owners(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Who a corrective action can be assigned to.

    The query lives in `app.services.capa_owners` so the report families offer
    the identical list — see that module for why supervisors and not workers.
    """
    return capa_owners.assignable_owners(db, current_user.org_id)


@router.get("/capa/my-actions")
def my_capa_actions(
    mine: Optional[bool] = Query(
        None, description="Only actions I own. Defaults to true for everyone except managers."
    ),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Open corrective actions, scoped to what this role is responsible for.

    Corrective actions are owned by supervisors, so a supervisor opening this
    list needs *their* actions — the ones they have to go and do. It previously
    returned every open CAPA in the organisation to anyone elevated, which meant
    the person accountable for three actions saw a list of forty and had no way
    to tell which were theirs.

    Managers keep the full list: they are monitoring completion, not doing it.
    `mine` overrides either default.
    """
    emp_id = db.execute(
        text("SELECT employee_id FROM users WHERE id = :uid"), {"uid": current_user.user_id}
    ).scalar()

    only_mine = mine if mine is not None else not _role_matches(current_user.role, MANAGER_ROLES)

    q = (
        db.query(CapaAction)
        .filter(CapaAction.organisation_id == current_user.org_id)
        .filter((CapaAction.status.is_(None)) | func.lower(CapaAction.status).notin_(["completed", "closed", "verified", "done"]))
    )
    if only_mine:
        q = q.filter(CapaAction.responsible_person_id == emp_id)
    rows = q.order_by(CapaAction.id.desc()).limit(100).all()
    return [
        {
            "id": c.id,
            "incident_id": c.incident_id,
            "action_type": c.action_type,
            "description": c.description,
            "responsible_person_id": c.responsible_person_id,
            # Who owns it. A manager looking at the full list needs the name to
            # chase it; the id alone is not actionable.
            "responsible_person_name": db.execute(
                text("SELECT full_name FROM employees WHERE id = :id"),
                {"id": c.responsible_person_id},
            ).scalar() if c.responsible_person_id else None,
            "due_date": c.due_date.isoformat() if c.due_date else None,
            "status": c.status,
            "priority_band": c.priority_band,
        }
        for c in rows
    ]


@router.post("/capa/{capa_id}/complete")
def complete_capa_action(
    capa_id: int,
    payload: CapaComplete,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Marks a CAPA action done — the responsible person, or a supervisor/manager, may close it."""
    capa = db.query(CapaAction).filter(
        CapaAction.id == capa_id, CapaAction.organisation_id == current_user.org_id
    ).first()
    if not capa:
        raise HTTPException(status_code=404, detail="CAPA action not found")

    emp_id = db.execute(
        text("SELECT employee_id FROM users WHERE id = :uid"), {"uid": current_user.user_id}
    ).scalar()
    is_owner = emp_id is not None and capa.responsible_person_id == emp_id
    if not is_owner and not _role_matches(current_user.role, ALL_ELEVATED_ROLES):
        raise HTTPException(status_code=403, detail="Not authorized to close this CAPA action")

    capa.status = "Completed"
    if payload.effectiveness_rating is not None:
        capa.effectiveness_rating = payload.effectiveness_rating
    db.flush()

    # Stage 05 -> 06. The incident leaves IMPROVE when its last outstanding
    # action closes, not when any one of them does — a partly-actioned incident
    # has not been improved yet.
    advanced_to = None
    if capa.incident_id:
        parent = db.query(Incident).filter(Incident.id == capa.incident_id).first()
        if (
            parent is not None
            and parent.workflow_status == "capa_open"
            and not _has_open_capa(db, parent.id)
        ):
            parent.workflow_status = "pending_verification"
            advanced_to = parent.workflow_status

    db.commit()
    db.refresh(capa)
    return {
        "id": capa.id,
        "status": capa.status,
        "effectiveness_rating": capa.effectiveness_rating,
        "incident_advanced_to": advanced_to,
    }
