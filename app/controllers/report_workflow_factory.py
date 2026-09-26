"""Builds an independent Worker→Supervisor→Manager workflow router per report type.

Each report type gets its OWN table and its OWN routes (/near-miss-workflow,
/unsafe-act-workflow, /risk-workflow). The state machine is defined once here so the
three stay behaviourally identical and a fix lands in all of them at the same time.

The flow, identical to incidents:

    worker  POST /report                    → reported
    supr    GET  /pending-review            (reported | acknowledged | under_investigation)
    supr    POST /{id}/acknowledge          → acknowledged
    supr    POST /{id}/investigate          → escalated (high/critical) | pending_approval
    supr    POST /{id}/escalate             → escalated
    mgr     GET  /manager-queue             (escalated | pending_approval)
    mgr     POST /{id}/approve-investigation→ capa_open | pending_verification | approved
    mgr     POST /{id}/verify-effectiveness → approved | capa_open (fix did not hold)
    mgr     POST /{id}/close                → closed
    any     GET  /next-actions              what is waiting on me, and the step it needs
    any     GET  /{id}/next-action          the eight-stage tracker for one record
    any     GET  /all                       the whole lifecycle, filterable by stage

This module does NOT touch incidents — /incident-workflow keeps its own controller so
the website's behaviour is unchanged.
"""
import json
from datetime import date, datetime
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Type

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import ValidationError
from sqlalchemy import text, func

from app.config.database import SessionLocal
from app.services import (
    capa_notify,
    capa_owners,
    event_assessment,
    events,
    report_next_action,
    workflow_stages,
)
from app.services.audit_log import record_audit
from app.services.events import catalogue
from app.services import department_scope
from app.utils import report_media
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import CurrentUser, get_current_user
from app.schemas.report_workflow import (
    ManagerApproveReport,
    ManagerCloseReport,
    ManagerVerifyReportEffectiveness,
    ReportCapaComplete,
    ReportListItem,
    ReportVerify,
    ReportWorkflowResponse,
    SupervisorAcknowledgeReport,
    SupervisorEscalateReport,
    SupervisorInvestigateReport,
)

# ── Role constants (same sets incident_workflow.py uses) ─────────────────────
WORKER_ROLES = {"Worker", "Employee", "Operator", "Technician"}
SUPERVISOR_ROLES = {"Supervisor", "Site Inspector", "Safety Manager", "Safety_Manager", "Site Engineer"}
MANAGER_ROLES = {"Manager", "HSE Manager", "Admin", "Superadmin", "Safety Manager", "Safety_Manager", "Director"}
AUDITOR_ROLES = {"Auditor"}

# Auditors are excluded from ALL_ELEVATED_ROLES on purpose — they verify at
# step 4, they do not investigate at step 2.
ALL_ELEVATED_ROLES = SUPERVISOR_ROLES | MANAGER_ROLES
ALL_READ_ROLES = SUPERVISOR_ROLES | MANAGER_ROLES | AUDITOR_ROLES

# Severities that jump straight to the manager instead of waiting for approval.
ESCALATING_SEVERITIES = {"high", "critical"}

SUPERVISOR_QUEUE_STATUSES = ["reported", "acknowledged", "under_investigation"]
# Stages 04, 05, 06 and 07 all sit with the manager in one form or another.
# `capa_open` is here so a record does not vanish from the manager's view for
# the length of a corrective action that may run 90 days.
MANAGER_QUEUE_STATUSES = [
    "escalated",             # 04 — needs a decision one level up
    "pending_approval",      # 04 — RCA awaiting sign-off
    "capa_open",             # 05 — visible, but the action is the assignee's
    "pending_verification",  # 06 — fix done, effectiveness unconfirmed
    "approved",              # 07 — verified, awaiting the lesson and closure
]


def _has_open_capa(db: Session, family: str, record_id: int) -> bool:
    """Is any corrective action for this record still outstanding?"""
    from app.models.capa_action import CapaAction

    return (
        db.query(CapaAction.id)
        .filter(CapaAction.subject_family == family, CapaAction.subject_id == record_id)
        .filter((CapaAction.status.is_(None)) | func.lower(CapaAction.status).notin_(["completed", "closed", "verified", "done"]))
        .first()
        is not None
    )


def _has_any_capa(db: Session, family: str, record_id: int) -> bool:
    from app.models.capa_action import CapaAction

    return (
        db.query(CapaAction.id)
        .filter(CapaAction.subject_family == family, CapaAction.subject_id == record_id)
        .first()
        is not None
    )


def _role_matches(user_role: str, allowed: set) -> bool:
    """Case-insensitive role check — DB stores 'operator', constants say 'Operator'."""
    return (user_role or "").strip().lower() in {r.lower() for r in allowed}


def _require_role(user_role: str, allowed: set, action: str) -> None:
    if not _role_matches(user_role, allowed):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user_role}' is not authorized to {action}",
        )


# A record is created at "reported" (see create_report below). Acknowledge and
# escalate used to skip this check — unlike investigate/verify/close — so a
# closed or approved record could be forced back to an earlier stage by an
# out-of-order call. Mirrors permit_workflow._require_state.
ACKNOWLEDGE_FROM = ("reported",)
ESCALATE_FROM = ("reported", "acknowledged", "under_investigation")


def _require_report_state(row, report_type: str, allowed: tuple, verb: str) -> None:
    if row.workflow_status in allowed:
        return
    st = workflow_stages.describe(report_type, row.workflow_status)
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            f"This record is at stage {st.get('stage_number')} "
            f"{st.get('stage_label') or row.workflow_status} and cannot be {verb}. "
            f"This applies to a record that is {' or '.join(allowed)}."
        ),
    )


def _employee_id_for(db: Session, user_id: int) -> Optional[int]:
    row = db.execute(
        text("SELECT employee_id FROM users WHERE id = :uid"), {"uid": user_id}
    ).mappings().first()
    return row["employee_id"] if row else None


def _station_id_for(db: Session, name: Optional[str], org_id: Optional[int]) -> Optional[int]:
    """Workers pick a station by name in the app; map it to an id, else leave unset."""
    if not name:
        return None
    row = db.execute(
        text(
            "SELECT id FROM working_stations "
            "WHERE station_name = :name AND organisation_id = :org_id"
        ),
        {"name": name, "org_id": org_id},
    ).mappings().first()
    return row["id"] if row else None


@dataclass(frozen=True)
class RowContext:
    """What a family's build_row needs beyond the payload.

    Risk has to turn the category the form sent into this organisation's own
    category name, which is a lookup — so the builders get the session and the
    caller's org rather than each family reaching for a global one.
    """

    db: Session
    org_id: Optional[int]


def _person_name(db: Session, employee_id: Optional[int]) -> Optional[str]:
    """employees.id -> full_name, for the one record being opened."""
    if not employee_id:
        return None
    row = db.execute(
        text("SELECT full_name FROM employees WHERE id = :id"),
        {"id": int(employee_id)},
    ).mappings().first()
    return row["full_name"] if row else None


def _station_name(db: Session, station_id: Optional[int]) -> Optional[str]:
    if not station_id:
        return None
    row = db.execute(
        text("SELECT station_name FROM working_stations WHERE id = :id"),
        {"id": int(station_id)},
    ).mappings().first()
    return row["station_name"] if row else None


def build_workflow_router(
    *,
    report_type: str,
    model: Type,
    prefix: str,
    tag: str,
    create_schema: Type,
    build_row: Callable[[Any, Dict[str, Any], "RowContext"], Dict[str, Any]],
    detail_fields: List[str],
    observed_at_field: str = "observed_date_time",
    noun: Optional[str] = None,
) -> APIRouter:
    """Return a fully wired router for one report type.

    `build_row` maps the validated payload to type-specific column values; everything
    shared (org, reporter, station, evidence, workflow state) is filled in here.
    `detail_fields` are the type-specific columns surfaced in the response `details`.
    `observed_at_field` names the column holding when the event was seen — near misses
    call it `event_date_time`, so it cannot be hardcoded.
    `noun` is what the record is called in a message shown to a person. It is
    separate from `tag`, which names the group in the OpenAPI docs: the mobile
    screens now surface these details verbatim, and "This Near Miss Workflow is
    at stage 5" is not a sentence to put in front of a supervisor.
    """
    noun = noun or report_type.replace("_", " ")
    router = APIRouter(prefix=prefix, tags=[tag])

    def _get(db: Session, record_id: int, org_id: Optional[int]):
        row = db.query(model).filter(model.id == record_id).first()
        if not row:
            raise HTTPException(status_code=404, detail=f"{noun.capitalize()} {record_id} not found")
        if org_id is not None and row.organisation_id not in (None, org_id):
            raise HTTPException(status_code=404, detail=f"{noun.capitalize()} {record_id} not found")
        return row

    def _respond(row, db: Optional[Session] = None) -> ReportWorkflowResponse:
        _stage = workflow_stages.describe(report_type, row.workflow_status)
        # Only the single-record read passes `db`. The list and transition
        # responses skip the two lookups: they render a queue, where an id is
        # never displayed, and paying per row for a name nobody sees is how a
        # list gets slow.
        _who = _person_name(db, row.reported_by) if db is not None else None
        _where = _station_name(db, row.location_station_id) if db is not None else None
        return ReportWorkflowResponse(
            id=row.id,
            report_type=report_type,
            workflow_status=row.workflow_status,
            severity=row.severity,
            description=row.description,
            location_station_id=row.location_station_id,
            reported_by=row.reported_by,
            reported_at=row.reported_at,
            acknowledged_at=row.acknowledged_at,
            investigation_completed_at=row.investigation_completed_at,
            escalated_at=row.escalated_at,
            approved_at=row.approved_at,
            closed_at=row.closed_at,
            root_cause=row.root_cause,
            immediate_actions_taken=row.immediate_actions_taken,
            escalation_reason=row.escalation_reason,
            closure_notes=row.closure_notes,
            auditor_verified_by=getattr(row, "auditor_verified_by", None),
            auditor_verified_at=getattr(row, "auditor_verified_at", None),
            verification_result=getattr(row, "verification_result", None),
            verification_notes=getattr(row, "verification_notes", None),
            # Stage 02 output — the same shape for every event family, so a
            # near miss can be ranked against an incident without special-casing.
            assessed_priority=getattr(row, "assessed_priority", None),
            assessed_label=getattr(row, "assessed_label", None),
            is_hipo=bool(getattr(row, "is_hipo", 0)),
            is_recurring_pattern=bool(getattr(row, "is_recurring_pattern", 0)),
            requires_systemic_rca=bool(getattr(row, "requires_systemic_rca", 0)),
            response_due_at=getattr(row, "response_due_at", None),
            min_investigator=getattr(row, "min_investigator", None),
            assessment_trace=getattr(row, "assessment_trace", None),
            # Where this record sits in the eight stages. Fields are named
            # explicitly rather than spread from describe(), which also returns
            # workflow_status and would collide with the kwarg above.
            stage=_stage.get("stage"),
            stage_number=_stage.get("stage_number"),
            stage_label=_stage.get("stage_label"),
            completed_stages=_stage.get("completed_stages"),
            total_stages=_stage.get("total_stages"),
            # Resolved for display. The reporter and the station were sent as
            # bare ids, so a supervisor opening a report saw "reported_by: 41"
            # and had no way to tell who had reported it or where.
            reported_by_name=_who,
            station_name=_where,
            # When it happened, as opposed to when it was typed in. Every
            # family has stored this since the forms grew a date picker; the
            # column is named differently per table, which is why it needs the
            # same indirection the writer uses.
            observed_at=getattr(row, observed_at_field, None),
            gps_latitude=getattr(row, "gps_latitude", None),
            gps_longitude=getattr(row, "gps_longitude", None),
            # Collected by the report forms and, until now, never read back:
            # the supervisor deciding whether to investigate could not see who
            # had witnessed the event.
            witnesses=getattr(row, "witnesses_json", None) or [],
            # The photos and videos the reporter attached. Collected by every
            # report form, uploaded, stored — and never sent back, so the
            # supervisor deciding what happened next could not look at them.
            evidence=getattr(row, "evidence_json", None) or [],
            hazard_still_present=getattr(row, "hazard_still_present", None),
            report_date=getattr(row, "report_date", None),
            created_at=getattr(row, "created_at", None),
            updated_at=getattr(row, "updated_at", None),
            # The rest of the supervisor's and manager's own work: the 5 Whys,
            # the lesson, the two signatures and the CAPA verification. All
            # written by the workflow verbs, none of it readable afterwards.
            five_why_analysis=getattr(row, "five_why_analysis", None),
            lessons_learned=getattr(row, "lessons_learned", None),
            supervisor_signature=getattr(row, "supervisor_signature", None),
            manager_signature=getattr(row, "manager_signature", None),
            investigation_started_at=getattr(row, "investigation_started_at", None),
            assessed_at=getattr(row, "assessed_at", None),
            capa_verified_at=getattr(row, "capa_verified_at", None),
            capa_verification_notes=getattr(row, "capa_verification_notes", None),
            capa_verification_failures=getattr(row, "capa_verification_failures", None),
            assigned_supervisor_name=(
                _person_name(db, getattr(row, "assigned_supervisor_id", None))
                if db is not None else None
            ),
            escalated_to_manager_name=(
                _person_name(db, getattr(row, "escalated_to_manager_id", None))
                if db is not None else None
            ),
            capa_verified_by_name=(
                _person_name(db, getattr(row, "capa_verified_by", None))
                if db is not None else None
            ),
            auditor_verified_by_name=(
                _person_name(db, getattr(row, "auditor_verified_by", None))
                if db is not None else None
            ),
            details={f: getattr(row, f, None) for f in detail_fields},
        )

    def _statuses_in_stage(stage_key: str) -> List[str]:
        """Every workflow_status this family maps onto one stage.

        Derived from the same status->stage table the responses use, so a filter
        chip and the rail it filters on can never disagree.
        """
        want = (stage_key or "").strip().upper()
        mapping = workflow_stages.FAMILY_MAPPINGS.get(report_type, {})
        return [status_name for status_name, key in mapping.items() if key == want]

    def _reference(record_id: int) -> str:
        """NEA-12 / UNS-12 / RIS-12 — the same three-letter form the closure
        event publishes, so a queue row and an audit trail entry name the record
        identically."""
        return f"{report_type.upper().replace('_', '')[:3]}-{record_id}"

    def _station_names(db: Session, rows) -> Dict[int, str]:
        """Station id -> name for a page of rows, in one query."""
        ids = {r.location_station_id for r in rows if r.location_station_id}
        if not ids:
            return {}
        found = db.execute(
            text("SELECT id, station_name FROM working_stations WHERE id IN :ids"),
            {"ids": tuple(ids)},
        ).mappings().all()
        return {r["id"]: r["station_name"] for r in found}

    def _list(rows) -> List[ReportListItem]:
        out = []
        for r in rows:
            # Derived once, the same way _respond does it. This used to call
            # stage_for twice and omit completed_stages and total_stages
            # entirely, so a queue card had no way to draw the stage rail.
            st = workflow_stages.describe(report_type, r.workflow_status)
            out.append(ReportListItem(
                id=r.id,
                report_type=report_type,
                workflow_status=r.workflow_status,
                severity=r.severity,
                description=r.description,
                location_station_id=r.location_station_id,
                reported_by=r.reported_by,
                reported_at=r.reported_at,
                acknowledged_at=r.acknowledged_at,
                created_at=r.created_at,
                # Queues rank on the assessed priority, not the reporter's
                # impression, so both are exposed in list views.
                assessed_priority=getattr(r, "assessed_priority", None),
                is_hipo=bool(getattr(r, "is_hipo", 0)),
                response_due_at=getattr(r, "response_due_at", None),
                stage=st.get("stage"),
                stage_number=st.get("stage_number"),
                stage_label=st.get("stage_label"),
                completed_stages=st.get("completed_stages") or [],
                total_stages=st.get("total_stages"),
            ))
        return out

    # ══════════════════════════════════════════════════════════════════════════
    # WORKER
    # ══════════════════════════════════════════════════════════════════════════
    @router.post("/report", response_model=ReportWorkflowResponse, status_code=201)
    async def worker_report_http(
        request: Request,
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        """Worker submits, with or without evidence files attached.

        Takes the raw request rather than a declared `create_schema` body so the
        multipart shape is accepted. The app switches to multipart the moment a
        photo or video is attached, and against a declared model FastAPI answered
        422 — so attaching evidence did not lose the file, it failed the whole
        report. See `app.utils.report_media`.

        Validation is not lost, only moved: the same schema is applied below, and
        a bad body still comes back as a 422 with Pydantic's own errors.
        """
        data, media_urls = await report_media.read_report_body(request, subdir=report_type)
        data = report_media.merge_media(data, media_urls)
        try:
            payload = create_schema(**data)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=json.loads(exc.json()))
        return worker_report(payload, db, current_user)

    def worker_report(
        payload: create_schema,  # type: ignore[valid-type]
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        """Create the record. Lands in the supervisor queue as `reported`.

        Kept as a plain function taking an already-validated payload because
        `event_drafts` submits a stored draft through it directly — see the note
        where it is attached to the router below.
        """
        now = datetime.now()
        data = payload.model_dump()

        typed_location = (data.get("location") or "").strip()
        station_id = data.get("location_station_id") or _station_id_for(
            db, typed_location, current_user.org_id
        )

        fields = {
            "organisation_id": current_user.org_id,
            "report_date": date.today(),
            observed_at_field: data.get("observed_date_time") or now,
            "location_station_id": station_id,
            "description": data.get("description"),
            "severity": (data.get("severity") or "medium").lower(),
            "reported_by": _employee_id_for(db, current_user.user_id),
            "hazard_still_present": data.get("hazard_still_present"),
            "witnesses_json": data.get("witnesses"),
            "evidence_json": data.get("photos"),
            "gps_latitude": data.get("gps_latitude"),
            "gps_longitude": data.get("gps_longitude"),
            "workflow_status": "reported",
            "reported_at": now,
        }
        # A family's own builder wins: near misses collect location_other from
        # an explicit "Other" box on the form, and that answer is better than
        # anything inferred here.
        fields.update(build_row(payload, data, RowContext(db=db, org_id=current_user.org_id)))

        # Fallback for the forms with a plain text box rather than an "Other"
        # option. _station_id_for matches on exact station_name, so a worker who
        # typed "Bay 4, Loading Dock" had their answer resolve to nothing and
        # then dropped — the reviewer opened a report with no location at all.
        # Kept only when no station matched, so the place is never in two
        # columns at once.
        if (
            typed_location
            and not station_id
            and not fields.get("location_other")
            and hasattr(model, "location_other")
        ):
            fields["location_other"] = typed_location

        row = model(**fields)
        db.add(row)
        # Flush rather than commit so the record has an id: the recurrence check
        # excludes the record itself, and without an id it would match nothing.
        db.flush()

        # ── Stage 02 ASSESS ──────────────────────────────────────────────────
        # Every event family is triaged the moment it is recorded, not just
        # incidents. This is what makes "the same 8 stages" true rather than a
        # slide claim.
        event_assessment.apply_to(row, event_assessment.assess(db, report_type, row))

        db.commit()
        db.refresh(row)
        return _respond(row)

    # Stage 01 -> 02. `worker_report` is a closure over this router's model and
    # schema, so it cannot be imported by name. Attaching it here lets
    # app/controllers/event_drafts.py submit a draft through the family's real
    # create path — with its validation, its station lookup and its stage 02
    # assessment — instead of a second implementation that would drift.
    router.create_from_payload = worker_report  # type: ignore[attr-defined]
    router.create_schema = create_schema        # type: ignore[attr-defined]

    @router.get("/my-reports", response_model=List[ReportListItem])
    def worker_my_reports(
        skip: int = 0,
        limit: int = Query(50, le=1000),
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        """A worker's own submissions, so they can track what happened to them."""
        emp_id = _employee_id_for(db, current_user.user_id)
        rows = (
            db.query(model)
            .filter(model.organisation_id == current_user.org_id)
            .filter(model.reported_by == emp_id)
            .order_by(model.id.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return _list(rows)

    # ══════════════════════════════════════════════════════════════════════════
    # SUPERVISOR
    # ══════════════════════════════════════════════════════════════════════════
    @router.get("/pending-review", response_model=List[ReportListItem])
    def supervisor_pending_review(
        skip: int = 0,
        limit: int = Query(50, le=1000),
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        _require_role(current_user.role, ALL_ELEVATED_ROLES, f"view pending {noun} reports")
        # Scoped to the reporter's department, the same rule incidents use: the
        # admin fixes a department on every employee, and only that
        # department's supervisor works its reports. Admins and auditors still
        # see the whole organisation.
        q = (
            db.query(model)
            .filter(model.organisation_id == current_user.org_id)
            .filter(model.workflow_status.in_(SUPERVISOR_QUEUE_STATUSES))
        )
        q = department_scope.apply_scope(q, model, "reported_by", db, current_user)
        rows = (
            q.order_by(model.id.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return _list(rows)

    @router.post("/{record_id}/acknowledge", response_model=ReportWorkflowResponse)
    def supervisor_acknowledge(
        record_id: int,
        payload: SupervisorAcknowledgeReport,
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        _require_role(current_user.role, ALL_ELEVATED_ROLES, f"acknowledge a {noun}")
        row = _get(db, record_id, current_user.org_id)
        _require_report_state(row, report_type, ACKNOWLEDGE_FROM, "acknowledged")
        from_status = row.workflow_status
        row.workflow_status = "acknowledged"
        row.acknowledged_at = datetime.now()
        supervisor_id = _employee_id_for(db, current_user.user_id)
        row.assigned_supervisor_id = supervisor_id
        record_audit(db, current_user.org_id, supervisor_id, "acknowledge", report_type, row.id, from_status, "acknowledged")
        db.commit()
        db.refresh(row)
        return _respond(row)

    @router.post("/{record_id}/start-investigation", response_model=ReportWorkflowResponse)
    def supervisor_start_investigation(
        record_id: int,
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        """Stage 03 -> 04. Opens the investigation before any findings exist.

        Without this, `under_investigation` was a status only a manager
        rejection could produce, so a record jumped from RESPOND straight to the
        end of INVESTIGATE and stage 04 was never observably occupied.
        """
        _require_role(current_user.role, ALL_ELEVATED_ROLES, f"investigate a {noun}")
        row = _get(db, record_id, current_user.org_id)

        if row.workflow_status not in ("acknowledged", "reported"):
            raise HTTPException(
                status_code=400,
                detail=f"Only an acknowledged {noun} can move into investigation",
            )

        now = datetime.now()
        row.workflow_status = "under_investigation"
        if row.investigation_started_at is None:
            row.investigation_started_at = now
        # Acknowledgement is a precondition of investigating; record it rather
        # than leaving a hole in the audit trail.
        if row.acknowledged_at is None:
            row.acknowledged_at = now
        if row.assigned_supervisor_id is None:
            row.assigned_supervisor_id = _employee_id_for(db, current_user.user_id)

        db.commit()
        db.refresh(row)
        return _respond(row)

    @router.post("/{record_id}/investigate", response_model=ReportWorkflowResponse)
    def supervisor_investigate(
        record_id: int,
        payload: SupervisorInvestigateReport,
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        """Record the RCA. High/critical goes straight to the manager; the rest waits
        for manager approval."""
        _require_role(current_user.role, ALL_ELEVATED_ROLES, f"investigate a {noun}")
        row = _get(db, record_id, current_user.org_id)
        now = datetime.now()

        if payload.root_cause is not None:
            row.root_cause = payload.root_cause
        if payload.five_why_analysis is not None:
            row.five_why_analysis = payload.five_why_analysis
        if payload.immediate_actions_taken is not None:
            row.immediate_actions_taken = payload.immediate_actions_taken
        if payload.supervisor_signature is not None:
            row.supervisor_signature = payload.supervisor_signature
        if payload.severity is not None:
            row.severity = payload.severity.lower()

        if row.investigation_started_at is None:
            row.investigation_started_at = now
        row.investigation_completed_at = now
        if row.assigned_supervisor_id is None:
            row.assigned_supervisor_id = _employee_id_for(db, current_user.user_id)

        # ── Stage 05 IMPROVE · raise the corrective action ────────────────────
        # WF-04: the CAPA inherits its type from the assessed priority, which
        # sets the deadline. Without severity potential and systemic risk it
        # still gets a type and a due date, just no 1-9 priority band.
        if payload.capa_description:
            from app.models.capa_action import CapaAction
            from app.services.capa_priority import prioritise

            if payload.capa_responsible_person_id:
                owner_in_org = db.execute(
                    text("SELECT id FROM employees WHERE id = :id AND organisation_id = :org_id"),
                    {"id": payload.capa_responsible_person_id, "org_id": current_user.org_id},
                ).scalar()
                if not owner_in_org:
                    raise HTTPException(status_code=404, detail="No such employee")

            prio = prioritise(
                severity_potential=payload.capa_severity_potential,
                systemic_risk=payload.capa_systemic_risk,
                capa_type=payload.capa_type,
                incident_priority=getattr(row, "assessed_priority", None),
                created_at=now,
            )
            capa = CapaAction(
                organisation_id=current_user.org_id,
                # incident_id stays null: this is not an incident. The
                # polymorphic pair is what links it back (migration 056).
                subject_family=report_type,
                subject_id=row.id,
                source=report_type,
                raised_by=_employee_id_for(db, current_user.user_id),
                action_type="Corrective",
                description=payload.capa_description,
                root_cause_addressed=payload.root_cause,
                responsible_person_id=payload.capa_responsible_person_id,
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
                capa_notify.notify(
                    db,
                    org_id=current_user.org_id,
                    employee_id=capa.responsible_person_id,
                    title=f"{capa.capa_ref} assigned to you",
                    message=f"{capa.description}\nDue {capa.due_date or 'not set'}.",
                    category="capa_assigned",
                    subject_ref=capa.capa_ref,
                )

        if (row.severity or "").lower() in ESCALATING_SEVERITIES:
            row.workflow_status = "escalated"
            row.escalated_at = now
            row.escalation_reason = (
                row.escalation_reason or f"Auto-escalated: severity is {row.severity}"
            )
        else:
            row.workflow_status = "pending_approval"

        # Re-assess with what the investigation established — the same reason
        # incidents reclassify here. A near miss whose investigated potential
        # turns out to be a fatality becomes a HIPO now, not at report time.
        event_assessment.apply_to(row, event_assessment.assess(db, report_type, row))

        db.commit()
        db.refresh(row)
        return _respond(row)

    @router.post("/{record_id}/escalate", response_model=ReportWorkflowResponse)
    def supervisor_escalate(
        record_id: int,
        payload: SupervisorEscalateReport,
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        _require_role(current_user.role, ALL_ELEVATED_ROLES, f"escalate a {noun}")
        row = _get(db, record_id, current_user.org_id)
        _require_report_state(row, report_type, ESCALATE_FROM, "escalated")
        from_status = row.workflow_status
        row.workflow_status = "escalated"
        row.escalated_at = datetime.now()
        row.escalation_reason = payload.escalation_reason
        if payload.escalated_to_manager_id is not None:
            row.escalated_to_manager_id = payload.escalated_to_manager_id
        record_audit(db, current_user.org_id, _employee_id_for(db, current_user.user_id), "escalate", report_type, row.id, from_status, "escalated")
        db.commit()
        db.refresh(row)
        return _respond(row)

    # ══════════════════════════════════════════════════════════════════════════
    # MANAGER
    # ══════════════════════════════════════════════════════════════════════════
    @router.get("/manager-queue", response_model=List[ReportListItem])
    def manager_queue(
        skip: int = 0,
        limit: int = Query(50, le=1000),
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        _require_role(current_user.role, MANAGER_ROLES, f"view the {noun} manager queue")
        # Department rule again: the manager of a department decides on that
        # department's reports.
        q = (
            db.query(model)
            .filter(model.organisation_id == current_user.org_id)
            .filter(model.workflow_status.in_(MANAGER_QUEUE_STATUSES))
        )
        q = department_scope.apply_scope(q, model, "reported_by", db, current_user)
        rows = (
            q.order_by(model.id.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return _list(rows)

    @router.post("/{record_id}/approve-investigation", response_model=ReportWorkflowResponse)
    def manager_approve_investigation(
        record_id: int,
        payload: ManagerApproveReport,
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        """Approve the supervisor's investigation, or send it back for redo.

        Approving ends stage 04. Where it goes next depends on whether there is
        anything to improve: outstanding corrective actions mean IMPROVE, actions
        already complete mean VERIFY, and an investigation that raised none has
        nothing to verify and goes straight to LEARN.
        """
        _require_role(current_user.role, MANAGER_ROLES, f"approve {noun} investigations")
        row = _get(db, record_id, current_user.org_id)
        if payload.approved:
            row.approved_at = datetime.now()
            if _has_open_capa(db, report_type, row.id):
                row.workflow_status = "capa_open"
            elif _has_any_capa(db, report_type, row.id):
                row.workflow_status = "pending_verification"
            else:
                row.workflow_status = "approved"
        else:
            row.workflow_status = "under_investigation"  # back to the supervisor
            row.approved_at = None
        db.commit()
        db.refresh(row)
        return _respond(row)

    @router.post("/{record_id}/verify-effectiveness", response_model=ReportWorkflowResponse)
    def manager_verify_effectiveness(
        record_id: int,
        payload: ManagerVerifyReportEffectiveness,
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        """Stage 06 VERIFY — confirm the corrective action actually worked.

        A negative verification is not a rejection of paperwork; it means the
        hazard is still live. The record returns to IMPROVE and its actions are
        reopened, because closing something whose fix did not hold is exactly
        what this stage exists to prevent.
        """
        _require_role(current_user.role, MANAGER_ROLES, f"verify {noun} corrective actions")
        row = _get(db, record_id, current_user.org_id)

        if row.workflow_status not in ("pending_verification", "capa_open"):
            raise HTTPException(
                status_code=400,
                detail=f"This {noun} has no corrective action awaiting verification",
            )
        if row.workflow_status == "capa_open" and _has_open_capa(db, report_type, row.id):
            raise HTTPException(
                status_code=400,
                detail="Corrective actions are still open — they must be completed before verification",
            )

        from app.models.capa_action import CapaAction

        now = datetime.now()
        if payload.effective:
            row.workflow_status = "approved"
            row.capa_verified_by = _employee_id_for(db, current_user.user_id)
            row.capa_verified_at = now
            row.capa_verification_notes = payload.verification_notes
        else:
            row.workflow_status = "capa_open"
            row.capa_verified_by = None
            row.capa_verified_at = None
            row.capa_verification_notes = payload.verification_notes
            row.capa_verification_failures = (row.capa_verification_failures or 0) + 1
            # A CAPA that did not work is not a completed CAPA. Leaving it closed
            # would let the record walk straight back to verification with
            # nothing having changed.
            db.query(CapaAction).filter(
                CapaAction.subject_family == report_type,
                CapaAction.subject_id == row.id,
                func.lower(CapaAction.status).in_(["completed", "closed", "verified", "done"]),
            ).update({"status": "Open"}, synchronize_session=False)

        db.commit()
        db.refresh(row)
        return _respond(row)

    @router.get("/capa/assignable-owners")
    def capa_assignable_owners(
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        """Who the corrective action raised at stage 04 can be assigned to.

        Without this the supervisor's investigation form had no owner picker, so
        every corrective action raised off a near miss, unsafe act or risk was
        created with `responsible_person_id` null. An unowned action reaches
        nobody's task list and nobody is accountable for it — which is the whole
        point of IMPROVE — and the record then sits in stage 05 until a manager
        happens to sign it off from their own queue.
        """
        _require_role(current_user.role, ALL_ELEVATED_ROLES, f"assign {noun} corrective actions")
        return capa_owners.assignable_owners(db, current_user.org_id)

    @router.get("/capa/my-actions")
    def my_capa_actions(
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        """Outstanding corrective actions raised against this report type."""
        from app.models.capa_action import CapaAction

        emp_id = _employee_id_for(db, current_user.user_id)
        q = (
            db.query(CapaAction)
            .filter(CapaAction.organisation_id == current_user.org_id)
            .filter(CapaAction.subject_family == report_type)
            .filter((CapaAction.status.is_(None)) | func.lower(CapaAction.status).notin_(["completed", "closed", "verified", "done"]))
        )
        if not _role_matches(current_user.role, ALL_ELEVATED_ROLES):
            q = q.filter(CapaAction.responsible_person_id == emp_id)
        return [
            {
                "id": c.id, "subject_family": c.subject_family, "subject_id": c.subject_id,
                "description": c.description, "due_date": c.due_date.isoformat() if c.due_date else None,
                "status": c.status, "priority_band": c.priority_band,
            }
            for c in q.order_by(CapaAction.id.desc()).limit(100).all()
        ]

    @router.post("/capa/{capa_id}/complete")
    def complete_capa_action(
        capa_id: int,
        payload: ReportCapaComplete,
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        """Stage 05 -> 06 once the last outstanding action closes.

        A partly-actioned record has not been improved yet, so the record only
        leaves IMPROVE when nothing is left open.
        """
        from app.models.capa_action import CapaAction

        capa = (
            db.query(CapaAction)
            .filter(CapaAction.id == capa_id)
            .filter(CapaAction.organisation_id == current_user.org_id)
            .filter(CapaAction.subject_family == report_type)
            .first()
        )
        if not capa:
            raise HTTPException(status_code=404, detail="CAPA action not found")

        emp_id = _employee_id_for(db, current_user.user_id)
        is_owner = emp_id is not None and capa.responsible_person_id == emp_id
        if not is_owner and not _role_matches(current_user.role, ALL_ELEVATED_ROLES):
            raise HTTPException(status_code=403, detail="Not authorized to close this CAPA action")

        capa.status = "Completed"
        if payload.effectiveness_rating is not None:
            capa.effectiveness_rating = payload.effectiveness_rating
        db.flush()

        advanced_to = None
        parent = db.query(model).filter(model.id == capa.subject_id).first()
        if (
            parent is not None
            and parent.workflow_status == "capa_open"
            and not _has_open_capa(db, report_type, parent.id)
        ):
            parent.workflow_status = "pending_verification"
            advanced_to = parent.workflow_status

        db.commit()
        return {
            "id": capa.id,
            "status": capa.status,
            "effectiveness_rating": capa.effectiveness_rating,
            "subject_advanced_to": advanced_to,
        }

    @router.post("/{record_id}/close", response_model=ReportWorkflowResponse)
    def manager_close(
        record_id: int,
        payload: ManagerCloseReport,
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        _require_role(current_user.role, MANAGER_ROLES, f"close a {noun}")
        row = _get(db, record_id, current_user.org_id)

        if row.workflow_status == "closed":
            raise HTTPException(status_code=400, detail=f"This {noun} is already closed")

        # Stage 08 is the end of the ring, not a shortcut across it. Closure
        # requires the record to have reached LEARN, meaning its RCA was
        # approved, its corrective actions completed and their effectiveness
        # verified. Closing straight out of capa_open was how a record could be
        # signed off with its fix still outstanding.
        if row.workflow_status != "approved":
            st = workflow_stages.describe(report_type, row.workflow_status)
            raise HTTPException(
                status_code=400,
                detail=(
                    f"This {noun} is at stage {st.get('stage_number')} "
                    f"{st.get('stage_label') or row.workflow_status} and cannot be closed yet. "
                    "It must clear investigation approval, corrective action and effectiveness "
                    "verification first."
                ),
            )

        row.workflow_status = "closed"
        row.closed_at = datetime.now()
        if payload.closure_notes is not None:
            row.closure_notes = payload.closure_notes
        if payload.lessons_learned is not None:
            row.lessons_learned = payload.lessons_learned
        if payload.manager_signature is not None:
            row.manager_signature = payload.manager_signature

        # ── Stage 08 CLOSE · the same cascade every family gets ──────────────
        # A closed near miss teaches what a closed incident teaches, so it
        # re-opens the linked hazard, raises a competence gap where the cause
        # was a person, schedules a follow-up walk and publishes the lesson.
        event_id = events.publish(
            db, catalogue.CLOSURE_EVENT_FOR.get(report_type, f"{report_type}Closed"),
            organisation_id=row.organisation_id,
            subject_family=report_type, subject_id=row.id,
            user_id=current_user.user_id,
            payload={
                "reference": f"{report_type.upper()[:3]}-{row.id}",
                "hazard_id": getattr(row, "hazard_id", None),
                "location_station_id": row.location_station_id,
                "priority": getattr(row, "assessed_priority", None),
                "is_hipo": bool(getattr(row, "is_hipo", 0)),
                "root_cause": row.root_cause,
                "root_cause_category": getattr(row, "root_cause_category", None),
                "lessons_learned": row.lessons_learned,
                "involved_employee_id": row.reported_by,
                "reported_by": row.reported_by,
            },
        )

        db.commit()
        db.refresh(row)

        # After the commit, on their own sessions.
        events.dispatch(SessionLocal, event_id)
        return _respond(row)

    # ══════════════════════════════════════════════════════════════════════════
    # AUDITOR — step 4 of the workflow chain, independent verification
    # ══════════════════════════════════════════════════════════════════════════
    @router.get("/audit-list", response_model=List[ReportListItem])
    def auditor_audit_list(
        skip: int = 0,
        limit: int = Query(50, le=1000),
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        """Records the auditor may independently verify on site.

        Closed records are the ones worth verifying — the auditor is confirming
        that a control someone signed off is actually real.
        """
        _require_role(current_user.role, ALL_READ_ROLES, f"view the {noun} audit list")
        rows = (
            db.query(model)
            .filter(model.organisation_id == current_user.org_id)
            .filter(model.workflow_status.in_(["pending_approval", "closed"]))
            .order_by(model.id.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return _list(rows)

    @router.post("/{record_id}/verify", response_model=ReportWorkflowResponse)
    def auditor_verify(
        record_id: int,
        payload: ReportVerify,
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        """Record independent verification against the original record.

        Only an auditor may do this, and it never changes workflow_status — the
        assurance layer observes the chain, it does not drive it.
        """
        _require_role(current_user.role, AUDITOR_ROLES, f"verify a {noun}")
        row = _get(db, record_id, current_user.org_id)

        row.auditor_verified_by = _employee_id_for(db, current_user.user_id)
        row.auditor_verified_at = datetime.now()
        row.verification_result = payload.verification_result
        row.verification_notes = payload.verification_notes
        db.commit()
        db.refresh(row)
        return _respond(row)

    # ══════════════════════════════════════════════════════════════════════════
    # SHARED
    # ══════════════════════════════════════════════════════════════════════════
    @router.get("/all", response_model=List[ReportListItem])
    def list_all(
        stage: Optional[str] = Query(None, description="One of the eight stage keys"),
        include_closed: bool = Query(True),
        skip: int = 0,
        limit: int = Query(100, le=300),
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        """Every record of this type, for a screen that browses the lifecycle.

        The two queues answer "what is waiting on me"; neither can show a record
        that has moved on, so a manager could not look back at what was closed
        last week without leaving the app. `stage` filters on the derived stage
        rather than the raw status, because the stage is what the screen's
        filter chips are labelled with.
        """
        _require_role(current_user.role, ALL_READ_ROLES, f"list {noun} reports")
        q = db.query(model).filter(model.organisation_id == current_user.org_id)
        if not include_closed:
            # NULL-safe: `!= 'closed'` is NULL for a row with no status, which
            # would drop it from the open list *and* the closed one, so a legacy
            # record with an unset status would exist in no view at all.
            q = q.filter(
                (model.workflow_status.is_(None)) | (model.workflow_status != "closed")
            )
        if stage:
            # Filtered in SQL, not after the fact: post-filtering a page would
            # silently return fewer rows than `limit` whenever the stage's
            # records sat further down the table than the page reached.
            wanted = _statuses_in_stage(stage)
            if not wanted:
                return []
            q = q.filter(model.workflow_status.in_(wanted))
        rows = q.order_by(model.id.desc()).offset(skip).limit(limit).all()
        return _list(rows)

    @router.get("/next-actions")
    def my_next_actions(
        mine_only: bool = Query(True, description="Only steps this role actually owns"),
        limit: int = Query(50, le=200),
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        """Every open record of this type waiting on this user, and the step it needs.

        The report families had queues that listed records but never said what
        was owed on one, so a near miss could sit in IMPROVE indefinitely with a
        single unsigned corrective action holding it and nothing on screen
        saying so. This is the same answer `/incident-workflow/next-actions`
        gives, from the same resolver, for the other three families.
        """
        # Department-scoped like the two queues above — "waiting on me" must not
        # list another department's work.
        q = (
            db.query(model)
            .filter(model.organisation_id == current_user.org_id)
            .filter(model.workflow_status != "closed")
        )
        q = department_scope.apply_scope(q, model, "reported_by", db, current_user)
        rows = q.order_by(model.id.desc()).limit(300).all()
        if not rows:
            return {"count": 0, "items": [], "mine_count": 0}

        # Open corrective actions in one query, so the IMPROVE rows can name
        # what is actually outstanding instead of saying "a corrective action".
        from app.models.capa_action import CapaAction

        capa_rows = (
            db.query(
                CapaAction.subject_id,
                func.count(CapaAction.id).label("open_count"),
                func.min(CapaAction.id).label("first_id"),
                func.min(CapaAction.description).label("first_description"),
                func.min(CapaAction.due_date).label("first_due"),
                # Who holds it, so the manager's card can say so and offer to
                # change it. Without this the only thing a card at IMPROVE could
                # do was sign the action off — a manager looking at an action
                # sitting unowned, or owned by the wrong person, had no way to
                # see either fact, let alone fix it.
                func.min(CapaAction.responsible_person_id).label("first_owner"),
            )
            .filter(CapaAction.subject_family == report_type)
            .filter(CapaAction.subject_id.in_([r.id for r in rows]))
            .filter(
                (CapaAction.status.is_(None))
                | func.lower(CapaAction.status).notin_(["completed", "closed", "verified", "done"])
            )
            .group_by(CapaAction.subject_id)
            .all()
        )
        capa_by_record = {c.subject_id: c for c in capa_rows}

        # One lookup for every owner across the whole queue, rather than a query
        # per card.
        owner_ids = [c.first_owner for c in capa_rows if c.first_owner]
        owner_names: dict = {}
        if owner_ids:
            owner_names = {
                r[0]: r[1]
                for r in db.execute(
                    text("SELECT id, full_name FROM employees WHERE id IN :ids"),
                    {"ids": tuple(set(owner_ids))},
                ).all()
            }

        station_names = _station_names(db, rows)
        now = datetime.now()
        # Who this caller is, so a record they have already handled can say so.
        # Without it a supervisor's own record vanished from their list the
        # moment they finished with it: the step moved to the manager, `is_mine`
        # went false, and the only trace left was an "all open" tab that does
        # not distinguish their work from anyone else's.
        my_employee_id = _employee_id_for(db, current_user.user_id)
        items = []
        mine_count = 0

        for r in rows:
            info = report_next_action.describe(report_type, r.workflow_status, current_user.role)
            nxt = info["next_action"]
            if not nxt:
                continue
            if info["is_mine"]:
                mine_count += 1
            elif mine_only:
                continue

            detail = nxt["detail"]
            subject = None
            capa = capa_by_record.get(r.id)
            if info["stage"] == workflow_stages.IMPROVE and capa:
                subject = {
                    # The id, not just the reference: a screen offering to sign
                    # the action off has to be able to address it.
                    "id": int(capa.first_id),
                    "reference": f"CAPA-{capa.first_id:06d}",
                    "description": (capa.first_description or "")[:120],
                    "due_date": capa.first_due.isoformat() if capa.first_due else None,
                    "open_count": int(capa.open_count),
                    "responsible_person_id": capa.first_owner,
                    "responsible_person_name": owner_names.get(capa.first_owner),
                }
                detail = (
                    f"{capa.open_count} corrective action"
                    f"{'s' if capa.open_count != 1 else ''} still open."
                )

            due = getattr(r, "response_due_at", None)
            waiting_since = r.reported_at or r.created_at
            items.append({
                "family": report_type,
                "id": r.id,
                "reference": _reference(r.id),
                "description": (r.description or "")[:140],
                "priority": getattr(r, "assessed_priority", None),
                "severity_label": getattr(r, "assessed_label", None),
                # The reporter's own severity, which the investigation form
                # pre-selects so the supervisor corrects it rather than
                # retyping it. Distinct from `priority`, which is what the
                # assessor concluded.
                "severity": r.severity,
                "workflow_status": r.workflow_status,
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
                # Already handled by this caller, whoever holds the step now.
                # `assigned_supervisor_id` is stamped on the first transition
                # and never overwritten, so this stays true for the person who
                # actually did the work rather than whoever touched it last.
                "handled_by_me": bool(
                    my_employee_id
                    and (
                        getattr(r, "assigned_supervisor_id", None) == my_employee_id
                        or getattr(r, "escalated_to_manager_id", None) == my_employee_id
                    )
                ),
                "subject": subject,
                "is_hipo": bool(getattr(r, "is_hipo", 0)),
                "is_recurring": bool(getattr(r, "is_recurring_pattern", 0)),
                "is_overdue": bool(due and due < now),
                "due_at": due.isoformat() if due else None,
                "station_name": station_names.get(r.location_station_id or 0),
                "waiting_since": waiting_since.isoformat() if waiting_since else None,
            })

        # Overdue first, then P1..P5, then longest waiting. An unassessed record
        # sorts last on priority but not out of the list — it still needs somebody.
        items.sort(key=lambda i: (
            not i["is_overdue"],
            i["priority"] or "P9",
            i["waiting_since"] or "9999",
        ))
        return {"count": len(items[:limit]), "items": items[:limit], "mine_count": mine_count}

    @router.get("/{record_id}/next-action")
    def next_action_detail(
        record_id: int,
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        """Stage tracker + the one outstanding step, for the record's own screen."""
        row = _get(db, record_id, current_user.org_id)
        info = report_next_action.describe(report_type, row.workflow_status, current_user.role)
        return {
            "family": report_type,
            "record_id": row.id,
            "reference": _reference(row.id),
            **info,
            "track": report_next_action.stage_track(report_type, row.workflow_status),
        }

    @router.get("/stats/summary")
    def workflow_stats(
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        rows = (
            db.query(model.workflow_status, model.id)
            .filter(model.organisation_id == current_user.org_id)
            .all()
        )
        counts: Dict[str, int] = {}
        for st, _ in rows:
            counts[st or "unknown"] = counts.get(st or "unknown", 0) + 1
        return {
            "report_type": report_type,
            "total": len(rows),
            "by_status": counts,
            "pending_supervisor": sum(counts.get(s, 0) for s in SUPERVISOR_QUEUE_STATUSES),
            "pending_manager": sum(counts.get(s, 0) for s in MANAGER_QUEUE_STATUSES),
        }

    @router.get("/{record_id}", response_model=ReportWorkflowResponse)
    def get_detail(
        record_id: int,
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        return _respond(_get(db, record_id, current_user.org_id), db)

    return router
