"""Permit to Work workflow (flow 6), on the same eight stages as every other
safety event.

    01 RECORD      a draft in event_drafts (family `permit`)
    02 ASSESS      requested | acknowledged — awaiting review and the gate check
    03 RESPOND     gate_blocked   — a hard gate failed; fix it before issue
    04 INVESTIGATE suspended      — work stopped, cause being established
    05 IMPROVE     issued | active — granted, controls attached and being relied on
    06 VERIFY      verified       — auditor confirmed those controls on site
    07 LEARN       expired        — work finished, close-out lesson owed
    08 CLOSE       closed | rejected | cancelled

    worker    POST /permit-workflow/request            → requested
    worker    GET  /permit-workflow/my-permits
    supr      GET  /permit-workflow/pending-review      (requested)
    supr      POST /{id}/acknowledge                    → acknowledged
    mgr       GET  /permit-workflow/manager-queue       (requested | acknowledged)
    mgr       POST /{id}/approve                        → issued    (status='Active')
    mgr       POST /{id}/reject                         → rejected  (status='Rejected')
    worker    POST /{id}/activate                       → active
    supr      POST /{id}/suspend                        → suspended
    supr      POST /{id}/resume                         → active
    worker    POST /{id}/complete-work                  → expired
    supr      POST /{id}/close                          → closed
    mgr       GET  /permit-workflow/active              (monitoring)
    auditor   GET  /permit-workflow/audit-list          (live permits to verify)
    auditor   POST /{id}/verify                         → verified, if the check passes

Writes to permits_to_work. Two status columns, deliberately:

  `status`          the website's business state (Pending / Active / Suspended /
                    Rejected / Closed). Six analytics aggregates count
                    status='Active' to mean "live permit", so its meaning is
                    left exactly as it was.
  `workflow_status` the permit's own state machine, and the column the eight
                    stages are derived from. Read outside this controller only by
                    gate_engine and one `requested` count in stubs.py.
"""
import json
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import CurrentUser, get_current_user
from app.controllers.workflow_common import (
    AUDITOR_ROLES,
    MANAGER_ROLES,
    SUPERVISOR_ROLES,
    ALL_ELEVATED_ROLES,
    ALL_READ_ROLES,
    employee_id_for,
    require_role,
    role_matches,
    station_id_for,
)
from app.models.permit_to_work import PermitToWork
from app.services import permit_next_action, workflow_stages
from app.services import department_scope
from app.services.gate_engine import evaluate_permit_gates
from app.schemas.permit_workflow import (
    PermitAcknowledge,
    PermitApprove,
    PermitClose,
    PermitListItem,
    PermitReject,
    PermitRequest,
    PermitSuspend,
    PermitVerify,
    PermitWorkflowResponse,
)

router = APIRouter(prefix="/permit-workflow", tags=["Permit Workflow"])

SUPERVISOR_QUEUE = ["requested"]

# `gate_blocked` belongs here, and leaving it out was a trap.
#
# A blocked approval moves the permit to stage 03 RESPOND — a control problem
# somebody has to fix — and the manager who pressed Approve is the person it
# went to. But the queue they pressed it from listed only `requested` and
# `acknowledged`, so the permit dropped out of their list the instant it
# blocked, and no other screen in the app lists `gate_blocked` at all. Four
# permits in this database are sitting there: visible on the monitoring tile as
# "Pending Review", absent from every queue that could act on them, unreachable
# forever.
#
# Both verbs the permit needs from here are already allowed from `gate_blocked`
# — approve (retry once the cause is fixed) and reject — so the only thing
# missing was showing it to the person holding it.
MANAGER_QUEUE = ["requested", "acknowledged", "gate_blocked"]

# Granted, being worked under, or worked under and since verified — the states
# in which a permit authorises work right now. Shared with gate_engine; see
# workflow_stages.PERMIT_LIVE_STATUSES for why it lives there.
LIVE_STATUSES = list(workflow_stages.PERMIT_LIVE_STATUSES)


# How early work may start against the stated window.
#
# `validity_start` is a MySQL DATETIME with no fractional seconds, and MySQL
# *rounds* rather than truncates on the way in: a permit raised at 19:35:46.9 to
# start "now" is stored as starting at 19:35:47, half a second in its own
# future. Activating it immediately — which is exactly what a worker raising a
# permit for the job in front of them does — was refused with "this permit is
# not valid until 19:35". The window is stated to the minute everywhere it is
# shown, so a minute is the honest tolerance; anything genuinely later than that
# is a permit whose window has not opened, which is what this check is for.
START_GRACE = timedelta(minutes=1)


def _require_within_validity(row: PermitToWork, verb: str) -> None:
    """Refuse to start or restart work outside the permit's validity window.

    A permit authorises work *for a stated period*. That period was recorded and
    reported everywhere — the trail shows it, the next-action list flags it — and
    enforced nowhere: `/activate` checked only that the status was `issued`, so a
    permit whose window closed yesterday activated with a 200 and the system then
    reported work as authorised under it. The gate engine hard-blocks issuance on
    six separate checks, which made this the open side door next to a very solid
    front one.

    Deliberately not applied to /verify or /close. An auditor finding an expired
    permit still live is exactly the sort of thing they are on site to record,
    and closing one out is how it stops being live — blocking either would leave
    a dead permit with no route to being dealt with.

    A permit carrying no window cannot be checked and is allowed through. That is
    a data problem worth its own fix rather than something to refuse here; six
    permits in this database have no `validity_end` at all.
    """
    now = datetime.now()

    if row.validity_end and now > row.validity_end:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    f"This permit expired on {row.validity_end:%d %b %Y at %H:%M} "
                    f"and cannot be {verb}. Raise a new permit for this work."
                ),
                "reason": "permit_expired",
                "validity_start": row.validity_start.isoformat() if row.validity_start else None,
                "validity_end": row.validity_end.isoformat(),
            },
        )

    if row.validity_start and now < row.validity_start - START_GRACE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    f"This permit is not valid until {row.validity_start:%d %b %Y at %H:%M} "
                    f"and cannot be {verb} yet."
                ),
                "reason": "permit_not_yet_valid",
                "validity_start": row.validity_start.isoformat(),
                "validity_end": row.validity_end.isoformat() if row.validity_end else None,
            },
        )


# Which states each pre-issue transition may be applied from.
#
# These three were the only verbs with no state check: acknowledge, approve and
# reject wrote their new state over whatever was there. That let a closed permit
# be rejected, a gate-blocked one be dragged back to `acknowledged`, and — the
# worst of the three — a finished permit be approved back into `Active`, which
# is the column six analytics aggregates read as "live work". Every other verb
# in this file already checked, so this is the rule they were missing rather
# than a new one.
#
# `gate_blocked` is deliberately in the approve and reject sets: a hard gate
# failure is a control problem someone fixes and then re-submits, and if the
# permit could never be approved or rejected afterwards it would be stranded.
ACKNOWLEDGE_FROM = ("requested",)
APPROVE_FROM = ("requested", "acknowledged", "gate_blocked")
REJECT_FROM = ("requested", "acknowledged", "gate_blocked")


def _require_state(row: PermitToWork, allowed: tuple, verb: str) -> None:
    if row.workflow_status in allowed:
        return
    st = workflow_stages.describe("permit", row.workflow_status)
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            f"Permit is at stage {st.get('stage_number')} "
            f"{st.get('stage_label') or row.workflow_status} and cannot be {verb}. "
            f"This applies to a permit that is {' or '.join(allowed)}."
        ),
    )


def _require_holder_or_elevated(
    db: Session, row: PermitToWork, current_user: CurrentUser, verb: str
) -> None:
    """The permit holder, or somebody who supervises the work.

    `/activate` and `/complete-work` are the two verbs the flow gives the
    worker, and they were the only two in this file with no authorisation of any
    kind — no role check and no check that the caller had anything to do with
    the permit. Any signed-in account could start work under somebody else's
    permit, and worse, end it: `complete-work` withdraws the authorisation while
    a crew may still be under it.

    Elevated roles are allowed through because the supervisor's permit screen is
    what actually drives both verbs today, and the site supervisor starting or
    finishing a job on the holder's behalf is the normal case.
    """
    if role_matches(current_user.role, ALL_ELEVATED_ROLES):
        return
    emp_id = employee_id_for(db, current_user.user_id)
    if emp_id and emp_id in (row.requested_by, row.issued_by, row.acknowledged_by):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            f"Only the permit holder or their supervisor can {verb} this permit."
        ),
    )


def _station_names(db: Session, rows) -> dict:
    """Station id -> name for a page of permits, in one query."""
    ids = {r.location_station_id for r in rows if r.location_station_id}
    if not ids:
        return {}
    found = db.execute(
        text("SELECT id, station_name FROM working_stations WHERE id IN :ids"),
        {"ids": tuple(ids)},
    ).mappings().all()
    return {r["id"]: r["station_name"] for r in found}


def _permit_ref(row) -> str:
    return f"PTW-{row.id:04d}"


def _get(db: Session, permit_id: int, org_id: Optional[int]) -> PermitToWork:
    q = db.query(PermitToWork).filter(PermitToWork.id == permit_id)
    row = q.first()
    if not row or (org_id is not None and row.organisation_id not in (None, org_id)):
        raise HTTPException(status_code=404, detail="Permit not found")
    return row


def _resolve_permit_type_id(db: Session, data: dict, org_id: Optional[int]) -> Optional[int]:
    if data.get("permit_type_id"):
        return data["permit_type_id"]
    name = data.get("permit_type")
    if name:
        row = db.execute(
            text("SELECT id FROM permit_types WHERE permit_type_name LIKE :n LIMIT 1"),
            {"n": f"%{name.replace('_', ' ')}%"},
        ).mappings().first()
        if row:
            return row["id"]
    row = db.execute(text("SELECT id FROM permit_types LIMIT 1")).mappings().first()
    return row["id"] if row else None


def _evidence_of(row) -> List[str]:
    """The attachments, whichever way the column happens to hold them.

    MySQL's JSON type comes back parsed through the ORM but as a string over
    raw SQL, and permits are written both ways in this codebase. Returning []
    for anything unrecognised keeps a malformed row from breaking the response
    for the whole queue.
    """
    raw = getattr(row, "evidence_json", None)
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    return [str(u) for u in raw] if isinstance(raw, list) else []


def _respond(row) -> PermitWorkflowResponse:
    # Derived from workflow_status on the way out, never stored — see
    # PERMIT_STATUS_STAGE for why the stage rides on workflow_status and not on
    # the `status` column the dashboards count.
    _stage = workflow_stages.describe("permit", row.workflow_status)
    return PermitWorkflowResponse(
        id=row.id,
        permit_ref=_permit_ref(row),
        permit_type_id=row.permit_type_id,
        workflow_status=row.workflow_status,
        stage=_stage.get("stage"),
        stage_number=_stage.get("stage_number"),
        stage_label=_stage.get("stage_label"),
        completed_stages=_stage.get("completed_stages") or [],
        total_stages=_stage.get("total_stages"),
        status=row.status,
        work_description=row.work_description,
        location_station_id=row.location_station_id,
        duration_requested_hours=row.duration_requested_hours,
        number_of_workers=row.number_of_workers,
        validity_start=row.validity_start,
        validity_end=row.validity_end,
        requested_by=row.requested_by,
        requested_at=row.requested_at,
        evidence=_evidence_of(row),
        acknowledged_by=row.acknowledged_by,
        acknowledged_at=row.acknowledged_at,
        supervisor_notes=row.supervisor_notes,
        approved_by=row.approved_by,
        approved_at=row.approved_at,
        rejected_at=row.rejected_at,
        rejection_reason=row.rejection_reason,
        auditor_verified_by=row.auditor_verified_by,
        auditor_verified_at=row.auditor_verified_at,
        verification_result=row.verification_result,
        verification_notes=row.verification_notes,
    )


def _list(rows) -> List[PermitListItem]:
    out = []
    for r in rows:
        st = workflow_stages.describe("permit", r.workflow_status)
        out.append(PermitListItem(
            id=r.id,
            permit_ref=_permit_ref(r),
            permit_type_id=r.permit_type_id,
            workflow_status=r.workflow_status,
            status=r.status,
            work_description=r.work_description,
            location_station_id=r.location_station_id,
            requested_by=r.requested_by,
            requested_at=r.requested_at,
            validity_end=r.validity_end,
            gate_status=r.gate_status,
            gate_blocked_reason=r.gate_blocked_reason,
            stage=st.get("stage"),
            stage_number=st.get("stage_number"),
            stage_label=st.get("stage_label"),
            completed_stages=st.get("completed_stages") or [],
            total_stages=st.get("total_stages"),
        ))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# WORKER
# ══════════════════════════════════════════════════════════════════════════════
@router.post("/request", response_model=PermitWorkflowResponse, status_code=201)
def worker_request_permit(
    payload: PermitRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    now = datetime.now()
    data = payload.model_dump()
    emp_id = employee_id_for(db, current_user.user_id)

    row = PermitToWork(
        organisation_id=current_user.org_id,
        permit_type_id=_resolve_permit_type_id(db, data, current_user.org_id),
        date_issued=data.get("date_issued") or date.today(),
        time_issued=data.get("time_issued"),
        location_station_id=(
            data.get("location_station_id")
            or station_id_for(db, data.get("location"), current_user.org_id)
        ),
        work_description=data.get("work_description"),
        duration_requested_hours=data.get("duration_requested_hours"),
        number_of_workers=data.get("number_of_workers"),
        validity_start=data.get("validity_start"),
        validity_end=data.get("validity_end"),
        issued_by=emp_id,
        status="Pending",
        workflow_status="requested",
        requested_by=emp_id,
        requested_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _respond(row)


@router.get("/my-permits", response_model=List[PermitListItem])
def worker_my_permits(
    skip: int = 0,
    limit: int = Query(50, le=1000),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    emp_id = employee_id_for(db, current_user.user_id)
    rows = (
        db.query(PermitToWork)
        .filter(PermitToWork.organisation_id == current_user.org_id)
        .filter(PermitToWork.requested_by == emp_id)
        .order_by(PermitToWork.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return _list(rows)


# ══════════════════════════════════════════════════════════════════════════════
# SUPERVISOR
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/pending-review", response_model=List[PermitListItem])
def supervisor_pending_review(
    skip: int = 0,
    limit: int = Query(50, le=1000),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, ALL_READ_ROLES, "view pending permits")
    q = (
        db.query(PermitToWork)
        .filter(PermitToWork.organisation_id == current_user.org_id)
        .filter(PermitToWork.workflow_status.in_(SUPERVISOR_QUEUE))
    )
    # Department rule: a permit belongs to the requester's department, so only
    # that department's supervisor and manager work it.
    q = department_scope.apply_scope(q, PermitToWork, "requested_by", db, current_user)
    rows = (
        q.order_by(PermitToWork.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return _list(rows)


@router.post("/{permit_id}/acknowledge", response_model=PermitWorkflowResponse)
def supervisor_acknowledge(
    permit_id: int,
    payload: PermitAcknowledge,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, ALL_ELEVATED_ROLES, "acknowledge permits")
    row = _get(db, permit_id, current_user.org_id)
    _require_state(row, ACKNOWLEDGE_FROM, "acknowledged")
    row.workflow_status = "acknowledged"
    row.acknowledged_at = datetime.now()
    row.acknowledged_by = employee_id_for(db, current_user.user_id)
    if payload.supervisor_notes is not None:
        row.supervisor_notes = payload.supervisor_notes
    db.commit()
    db.refresh(row)
    return _respond(row)


# ══════════════════════════════════════════════════════════════════════════════
# MANAGER
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/manager-queue", response_model=List[PermitListItem])
def manager_queue(
    skip: int = 0,
    limit: int = Query(50, le=1000),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, MANAGER_ROLES, "view the permit manager queue")
    q = (
        db.query(PermitToWork)
        .filter(PermitToWork.organisation_id == current_user.org_id)
        .filter(PermitToWork.workflow_status.in_(MANAGER_QUEUE))
    )
    # Department rule: a permit belongs to the requester's department, so only
    # that department's supervisor and manager work it.
    q = department_scope.apply_scope(q, PermitToWork, "requested_by", db, current_user)
    rows = (
        q.order_by(PermitToWork.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return _list(rows)


@router.post("/{permit_id}/approve", response_model=PermitWorkflowResponse)
def manager_approve(
    permit_id: int,
    payload: PermitApprove,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, MANAGER_ROLES, "approve permits")
    row = _get(db, permit_id, current_user.org_id)
    # Checked before the gates run: re-evaluating a closed permit writes a gate
    # verdict and a decision-log entry for work that finished weeks ago.
    _require_state(row, APPROVE_FROM, "approved")

    # ── The Integration Spine runs here ──────────────────────────────────────
    # Permit issuance is the gate point the whole WF-06/08/09 chain feeds. A
    # blocked verdict stops issuance outright: the permit stays where it is and
    # the reason is recorded on the record and in gate_decision_log.
    evaluation = evaluate_permit_gates(
        db,
        current_user.org_id,
        row,
        evaluated_by=employee_id_for(db, current_user.user_id),
    )
    row.gate_status = evaluation.overall
    row.gate_checked_at = datetime.now()
    row.gate_blocked_reason = "; ".join(evaluation.blocked_reasons) or None

    if evaluation.overall == "block":
        # Stage 03 RESPOND. A hard gate failure is a control problem someone has
        # to fix before the work can be granted — the permit is not simply still
        # "requested", it is waiting on a corrective response.
        row.workflow_status = "gate_blocked"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Permit blocked by the deterministic gate engine.",
                "gate_status": evaluation.overall,
                "blocked_reasons": evaluation.blocked_reasons,
                "gates": [
                    {"gate_key": g.gate_key, "verdict": g.verdict, "reason": g.reason, "hard": g.hard}
                    for g in evaluation.gates
                ],
            },
        )

    # Stage 05 IMPROVE — granted, with its control set attached, but nobody is
    # working under it yet. Activation (stage 06) is the separate act of
    # starting the job.
    row.workflow_status = "issued"
    row.status = "Active"  # website dashboard counts active permits by this field
    row.approved_at = datetime.now()
    row.approved_by = employee_id_for(db, current_user.user_id)
    if payload.validity_start is not None:
        row.validity_start = payload.validity_start
    if payload.validity_end is not None:
        row.validity_end = payload.validity_end
    db.commit()
    db.refresh(row)
    return _respond(row)


@router.post("/{permit_id}/activate", response_model=PermitWorkflowResponse)
def activate_permit(
    permit_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Work starts under the permit. Still stage 05.

    An issued permit and one being worked under are different things — a granted
    authorisation versus controls actually being relied on — but neither has been
    checked by anyone, so both sit at IMPROVE. Only /verify advances the stage.
    """
    row = _get(db, permit_id, current_user.org_id)
    _require_holder_or_elevated(db, row, current_user, "start work under")
    if row.workflow_status not in ("issued", "approved"):
        raise HTTPException(
            status_code=400, detail="Only an issued permit can be activated"
        )
    _require_within_validity(row, "activated")
    row.workflow_status = "active"
    row.status = "Active"
    db.commit()
    db.refresh(row)
    return _respond(row)


@router.post("/{permit_id}/suspend", response_model=PermitWorkflowResponse)
def suspend_permit(
    permit_id: int,
    payload: PermitSuspend,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Stage 05/06 -> 04. Work stops and the cause is established.

    This is the permit's genuine INVESTIGATE state. The gate evaluation before
    issue is triage, not investigation — this is the case where something went
    wrong under a live permit and nobody goes back in until it is understood.

    A verified permit is suspendable like any other: passing an on-site check
    earlier does not make the work immune to stopping.
    """
    require_role(current_user.role, ALL_ELEVATED_ROLES, "suspend permits")
    row = _get(db, permit_id, current_user.org_id)
    if row.workflow_status not in LIVE_STATUSES:
        raise HTTPException(
            status_code=400, detail="Only a live permit can be suspended"
        )
    row.workflow_status = "suspended"
    row.status = "Suspended"
    row.suspension_reason = payload.reason
    db.commit()
    db.refresh(row)
    return _respond(row)


@router.post("/{permit_id}/resume", response_model=PermitWorkflowResponse)
def resume_permit(
    permit_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Stage 04 -> 05. The cause was established and work may restart.

    Back to `active`, never straight to `verified`: a verification made before
    the stoppage says nothing about the controls now, so the permit has to be
    checked again to reach stage 06.
    """
    require_role(current_user.role, ALL_ELEVATED_ROLES, "resume permits")
    row = _get(db, permit_id, current_user.org_id)
    if row.workflow_status != "suspended":
        raise HTTPException(status_code=400, detail="Permit is not suspended")
    # A suspension can outlast the window it was suspended within. Restarting
    # then is starting work on an expired permit by a slower route.
    _require_within_validity(row, "resumed")
    row.workflow_status = "active"
    row.status = "Active"
    db.commit()
    db.refresh(row)
    return _respond(row)


@router.post("/{permit_id}/complete-work", response_model=PermitWorkflowResponse)
def complete_permit_work(
    permit_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Stage 05/06 -> 07. Work is finished; the permit is spent and owes its lesson.

    Writes `work_complete`. It used to write `expired`, which read naturally
    enough — a spent permit is no longer an authorisation anyone can rely on —
    but that word was simultaneously the mapped status for a permit whose
    validity window ran out, which is a different situation with a different
    owed step. Migration 067 separated them.

    Verification is not required to finish work: auditors sample live permits,
    they do not check every one. A permit completed without ever being verified
    simply never occupied stage 06, which is the honest record of what happened.
    """
    row = _get(db, permit_id, current_user.org_id)
    _require_holder_or_elevated(db, row, current_user, "finish work under")
    if row.workflow_status not in LIVE_STATUSES:
        raise HTTPException(
            status_code=400, detail="Only a live permit can be completed"
        )
    row.workflow_status = "work_complete"
    db.commit()
    db.refresh(row)
    return _respond(row)


@router.post("/{permit_id}/reject", response_model=PermitWorkflowResponse)
def manager_reject(
    permit_id: int,
    payload: PermitReject,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, MANAGER_ROLES, "reject permits")
    row = _get(db, permit_id, current_user.org_id)
    _require_state(row, REJECT_FROM, "rejected")
    row.workflow_status = "rejected"
    row.status = "Rejected"
    row.rejected_at = datetime.now()
    row.rejection_reason = payload.rejection_reason
    db.commit()
    db.refresh(row)
    return _respond(row)


@router.get("/active", response_model=List[PermitListItem])
def active_permits(
    skip: int = 0,
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Live permits — the manager's monitoring view."""
    require_role(current_user.role, ALL_READ_ROLES, "monitor active permits")
    rows = (
        db.query(PermitToWork)
        .filter(PermitToWork.organisation_id == current_user.org_id)
        .filter(PermitToWork.workflow_status.in_(LIVE_STATUSES))
        .order_by(PermitToWork.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return _list(rows)


# ══════════════════════════════════════════════════════════════════════════════
# AUDITOR
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/audit-list", response_model=List[PermitListItem])
def auditor_audit_list(
    skip: int = 0,
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Live permits the auditor checks are valid and physically displayed on site.

    Already-verified permits stay on the list: verification is a sampling check
    on live work, and a permit can be re-checked while the work continues.
    """
    require_role(current_user.role, AUDITOR_ROLES | MANAGER_ROLES, "audit permits")
    rows = (
        db.query(PermitToWork)
        .filter(PermitToWork.organisation_id == current_user.org_id)
        .filter(PermitToWork.workflow_status.in_(LIVE_STATUSES))
        .order_by(PermitToWork.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return _list(rows)


@router.post("/{permit_id}/verify", response_model=PermitWorkflowResponse)
def auditor_verify(
    permit_id: int,
    payload: PermitVerify,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Stage 05 -> 06. The auditor confirms on site that the controls are holding.

    This is the only way a permit reaches VERIFY. It used to record the result
    and leave `workflow_status` untouched, so verification changed nothing a
    dashboard could see and every live permit sat at stage 06 regardless.

    Only a passing check advances the permit. An `invalid` or `not_displayed`
    result is a finding on live work, so the permit stays exactly where it is and
    a human decides whether to suspend it — the check does not stop the job by
    itself, and it must not read as a pass either.
    """
    require_role(current_user.role, AUDITOR_ROLES | MANAGER_ROLES, "verify permits")
    row = _get(db, permit_id, current_user.org_id)

    # Verifying a finished or closed permit would drag it back from LEARN/CLOSE
    # to VERIFY and undo its close-out. On-site verification only means something
    # while the work is live.
    if row.workflow_status not in LIVE_STATUSES:
        st = workflow_stages.describe("permit", row.workflow_status)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Permit is at stage {st.get('stage_number')} "
                f"{st.get('stage_label') or row.workflow_status} — on-site verification "
                "applies to live work only."
            ),
        )

    row.auditor_verified_by = employee_id_for(db, current_user.user_id)
    row.auditor_verified_at = datetime.now()
    row.verification_result = payload.verification_result
    if payload.verification_notes is not None:
        row.verification_notes = payload.verification_notes

    if str(payload.verification_result or "").strip().lower() == "valid":
        row.workflow_status = "verified"

    db.commit()
    db.refresh(row)
    return _respond(row)


@router.post("/{permit_id}/close", response_model=PermitWorkflowResponse)
def supervisor_close(
    permit_id: int,
    payload: PermitClose,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Closes out a permit at end of work. Sets status='Closed', which is what the
    PTW Compliance Rate counts as "properly closed", and records whether the work
    deviated from the permit (drives LOTO Compliance % and Permit Deviation Rate).
    """
    require_role(current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES, "close permits")
    row = _get(db, permit_id, current_user.org_id)

    if row.workflow_status == "closed":
        raise HTTPException(status_code=400, detail="Permit is already closed")

    # Stage 08 is the end of the ring. A permit still being worked under has not
    # reached LEARN, and closing it out would record a close-out for work that is
    # still happening. Rejected permits are already terminal and skip this.
    # `expired` is included alongside the completed state on purpose: a permit
    # that lapsed while still live must have a route to close-out, or it stays
    # live forever. See migration 067 for how the two came to be separate.
    if row.workflow_status not in ("work_complete", "expired", "rejected", "cancelled"):
        st = workflow_stages.describe("permit", row.workflow_status)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Permit is at stage {st.get('stage_number')} "
                f"{st.get('stage_label') or row.workflow_status} and cannot be closed yet. "
                "Complete the work first so the permit reaches close-out."
            ),
        )

    def _yes_no(value: str) -> str:
        return "Yes" if str(value or "").strip().lower() in ("yes", "true", "1") else "No"

    row.status = "Closed"
    row.workflow_status = "closed"
    row.deviation_reported = _yes_no(payload.deviation_reported)
    row.incident_occurred = _yes_no(payload.incident_occurred)
    row.work_start_actual = payload.work_start_actual or row.work_start_actual
    # Falling back to "now" means a closed permit always has an end time for the
    # duration analytics, even if the supervisor did not type one in.
    row.work_end_actual = payload.work_end_actual or row.work_end_actual or datetime.now()
    if payload.supervisor_notes is not None:
        row.supervisor_notes = payload.supervisor_notes

    db.commit()
    db.refresh(row)
    return _respond(row)


# ══════════════════════════════════════════════════════════════════════════════
# SHARED
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/next-actions")
def my_next_actions(
    mine_only: bool = Query(True, description="Only steps this role actually owns"),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Every open permit waiting on this user, and the exact step it needs.

    The permit half of the same question `/incident-workflow/next-actions` and
    `/near-miss-workflow/next-actions` answer. Permits already carried all eight
    stages in their responses, but nothing said *who* owed the next step, so a
    permit could sit issued-but-never-activated, or active with its controls
    unverified, and no screen would surface it.
    """
    rows = (
        db.query(PermitToWork)
        .filter(PermitToWork.organisation_id == current_user.org_id)
        .filter(PermitToWork.workflow_status.notin_(["closed", "cancelled", "rejected"]))
        .order_by(PermitToWork.id.desc())
        .limit(300)
        .all()
    )
    if not rows:
        return {"count": 0, "items": [], "mine_count": 0}

    stations = _station_names(db, rows)
    now = datetime.now()
    items: List[dict] = []
    mine_count = 0

    for r in rows:
        info = permit_next_action.describe(r.workflow_status, current_user.role)
        nxt = info["next_action"]
        if not nxt:
            continue
        if info["is_mine"]:
            mine_count += 1
        elif mine_only:
            continue

        # A permit whose validity has run out while still open is the one an
        # admin most needs to see — work may be continuing under a dead permit.
        expired = bool(r.validity_end and r.validity_end < now
                       and r.workflow_status in LIVE_STATUSES)
        items.append({
            "family": "permit",
            "id": r.id,
            "reference": _permit_ref(r),
            "description": (r.work_description or "")[:140],
            "permit_type_id": r.permit_type_id,
            "workflow_status": r.workflow_status,
            "stage": info["stage"],
            "stage_number": info["stage_number"],
            "stage_label": info["stage_label"],
            "action": nxt["action"],
            "detail": nxt["detail"],
            "cta": nxt["cta"],
            "route": nxt["route"],
            "unblocks": nxt["unblocks"],
            "owner_role": nxt["owner_role"],
            "is_mine": info["is_mine"],
            "can_act": info["can_act"],
            "station_name": stations.get(r.location_station_id or 0),
            "validity_start": r.validity_start.isoformat() if r.validity_start else None,
            "validity_end": r.validity_end.isoformat() if r.validity_end else None,
            "is_overdue": expired,
            "auditor_verified": bool(getattr(r, "auditor_verified_at", None)),
            "waiting_since": r.created_at.isoformat() if r.created_at else None,
        })

    # Permits past their validity first — those are the live safety problem —
    # then by stage, then oldest waiting.
    items.sort(key=lambda i: (
        not i["is_overdue"],
        i["stage_number"] or 99,
        i["waiting_since"] or "9999",
    ))
    return {"count": len(items[:limit]), "items": items[:limit], "mine_count": mine_count}


@router.get("/{permit_id}/next-action")
def permit_next_step(
    permit_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Stage tracker + the one outstanding step, for the permit's own screen."""
    row = _get(db, permit_id, current_user.org_id)
    info = permit_next_action.describe(row.workflow_status, current_user.role)
    return {
        "family": "permit",
        "record_id": row.id,
        "reference": _permit_ref(row),
        **info,
        "track": permit_next_action.stage_track(row.workflow_status),
    }


@router.get("/stats/summary")
def permit_stats(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    rows = (
        db.query(PermitToWork.workflow_status)
        .filter(PermitToWork.organisation_id == current_user.org_id)
        .all()
    )
    counts = {}
    for (st,) in rows:
        counts[st or "unknown"] = counts.get(st or "unknown", 0) + 1
    return {
        "total": len(rows),
        "by_status": counts,
        "pending_supervisor": sum(counts.get(s, 0) for s in SUPERVISOR_QUEUE),
        "pending_manager": sum(counts.get(s, 0) for s in MANAGER_QUEUE),
        "active": counts.get("approved", 0),
    }


@router.get("/{permit_id}", response_model=PermitWorkflowResponse)
def get_permit(
    permit_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    return _respond(_get(db, permit_id, current_user.org_id))
