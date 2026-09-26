"""Hazard register workflow (flow 5), on the same eight stages as every other
safety event.

    01 RECORD   a draft in event_drafts (family `hazard_register`)
    02 ASSESS   open              — logged, awaiting triage
    03 RESPOND  interim_control   — temporary control while the permanent one is designed
    04 INVESTIGATE under_review   — establishing what the real control must be
    05 IMPROVE  controls_planned  — permanent controls specified, work outstanding
    06 VERIFY   pending_verification
    07 LEARN    controlled        — control confirmed effective, lesson owed
    08 CLOSE    closed

    worker/supr  POST /hazard-register/log                → open
    any          GET  /hazard-register                    (register, filterable)
    worker       GET  /hazard-register/my-logs
    any          GET  /hazard-register/next-actions       (what is waiting on me)
    any          GET  /hazard-register/{id}
    any          GET  /hazard-register/{id}/next-action   (stage track + step)
    supr/mgr     POST /{id}/assess                        → interim_control | under_review
    supr/mgr     POST /{id}/interim-control               → interim_control
    supr/mgr     POST /{id}/start-review                  → under_review
    supr/mgr     POST /{id}/findings                      (root cause, stays under_review)
    supr/mgr     POST /{id}/plan-controls                 → controls_planned
    supr/mgr     POST /{id}/submit-verification           → pending_verification
    supr/mgr     POST /{id}/verify-controls               → controlled | back to controls_planned
    supr/mgr     POST /{id}/lesson                        (stays controlled)
    supr/mgr     POST /{id}/close                         → closed
    supr/mgr     POST /{id}/review                        (pre-stage escape hatch)
    auditor      GET  /hazard-register/audit-list         (hazards still being managed)
    auditor      POST /{id}/verify                        → records that it is being managed

Writes to the `hazards` register. The website's catalog reads (hazard_name / severity /
probability) are untouched; the lifecycle rides on the additive columns from
migrations 031 and 066.

Note this is the *standing register*, family `hazard_register`. The worker-reported
hazard is family `hazard` on `risk_reports` and runs the report workflow — two
different things that were previously pointed at the same stage mapping, which is
why every register entry resolved to no stage at all.

**Why explicit stage verbs and not one status setter.** `/review` could already
put a hazard into any state, but it recorded only `reviewed_by` and a single
notes column, so nothing distinguished "a guard was fitted" from "someone typed
controlled". Each verb below writes the columns its own stage owns, which is
what makes the trail on the web console reconstructable at all.
"""
from datetime import datetime
from typing import Dict, List, Optional, Sequence

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import CurrentUser, get_current_user
from app.controllers.workflow_common import (
    AUDITOR_ROLES,
    MANAGER_ROLES,
    ALL_ELEVATED_ROLES,
    employee_id_for,
    require_role,
    station_id_for,
)
from app.models.hazard import Hazard
from app.utils import report_media
from app.services import risk_assessment as risk_assessment_svc
from app.services import department_scope, event_assessment, hazard_next_action, workflow_stages
from app.services.audit_log import record_audit
from app.schemas.hazard_register import (
    HIERARCHY,
    HazardAssess,
    HazardClose,
    HazardInterimControl,
    HazardLesson,
    HazardLog,
    HazardNextActionResponse,
    HazardPlanControls,
    HazardRegisterResponse,
    HazardReview,
    HazardReviewFindings,
    HazardStartReview,
    HazardSubmitVerification,
    HazardVerify,
    HazardVerifyControls,
)

# No prefix baked in: main.py mounts this twice, at /unsafe-act-register
# (the family's name since 078) and at /hazard-register (legacy, kept so
# already-shipped mobile builds keep working).
router = APIRouter(tags=["Unsafe Act Register"])

# Everything that is still being managed — i.e. has not reached CLOSE. The
# auditor's list and the "open" count both read this, so a hazard sitting in any
# of the middle stages stays visible instead of silently dropping out.
OPEN_STATUSES = [
    "open", "interim_control", "under_review", "controls_planned", "pending_verification",
]
VALID_STATUSES = {
    "open",                 # 02 ASSESS
    "interim_control",      # 03 RESPOND
    "under_review",         # 04 INVESTIGATE
    "controls_planned",     # 05 IMPROVE
    "pending_verification", # 06 VERIFY
    "controlled",           # 07 LEARN
    "closed",               # 08 CLOSE
}


def _get(db: Session, hazard_id: int, org_id: Optional[int]) -> Hazard:
    row = db.query(Hazard).filter(Hazard.id == hazard_id).first()
    if not row or (org_id is not None and row.organisation_id not in (None, org_id)):
        raise HTTPException(status_code=404, detail="Unsafe act not found")
    return row


def _require_stage(row: Hazard, allowed: Sequence[str], what: str) -> None:
    """Refuse a stage verb the hazard is not actually at.

    Stated as a stage rather than a status because that is what the client
    renders — telling a supervisor the hazard is "at stage 4 Investigate" is
    actionable in a way that "register_status is under_review" is not.
    """
    if row.register_status in allowed:
        return
    st = workflow_stages.describe("hazard_register", row.register_status)
    raise HTTPException(
        status_code=400,
        detail=(
            f"Cannot {what}: this unsafe act is at stage {st.get('stage_number') or '?'} "
            f"{st.get('stage_label') or row.register_status}."
        ),
    )


# ══════════════════════════════════════════════════════════════════════════════
# Response assembly
# ══════════════════════════════════════════════════════════════════════════════
def _name_map(db: Session, employee_ids: Sequence[Optional[int]]) -> Dict[int, str]:
    """employees.id -> full_name for a batch of rows.

    One query per list rather than one per row: the register list is the
    auditor's landing screen and used to issue no lookups at all, so every
    person column rendered as a bare integer.
    """
    ids = sorted({int(i) for i in employee_ids if i})
    if not ids:
        return {}
    rows = db.execute(
        text("SELECT id, full_name FROM employees WHERE id IN :ids"),
        {"ids": tuple(ids)},
    ).mappings().all()
    return {r["id"]: r["full_name"] for r in rows}


def _lookup_maps(db: Session, rows: Sequence[Hazard]) -> Dict[str, Dict[int, str]]:
    # Every column holding an employee id, not just the three that had names.
    # One query covers the lot, so adding the rest costs nothing.
    people = _name_map(db, [
        getattr(r, f, None)
        for r in rows
        for f in (
            "logged_by", "reviewed_by", "control_owner_id", "assessed_by",
            "interim_control_by", "controls_planned_by", "controls_verified_by",
            "lesson_captured_by", "closed_by", "auditor_verified_by",
        )
    ])

    station_ids = sorted({r.location_station_id for r in rows if r.location_station_id})
    stations: Dict[int, str] = {}
    if station_ids:
        stations = {
            s["id"]: s["station_name"]
            for s in db.execute(
                text("SELECT id, station_name FROM working_stations WHERE id IN :ids"),
                {"ids": tuple(station_ids)},
            ).mappings().all()
        }

    category_ids = sorted({r.category_id for r in rows if r.category_id})
    categories: Dict[int, str] = {}
    if category_ids:
        categories = {
            c["id"]: c["category_name"]
            for c in db.execute(
                text("SELECT id, category_name FROM hazard_categories WHERE id IN :ids"),
                {"ids": tuple(category_ids)},
            ).mappings().all()
        }

    return {"people": people, "stations": stations, "categories": categories}


def _respond(row: Hazard, maps: Optional[Dict[str, Dict[int, str]]] = None) -> HazardRegisterResponse:
    out = HazardRegisterResponse.model_validate(row)
    out.reference = f"HAZ-{row.id}"

    # Derived on the way out from register_status, never stored, so the stage
    # cannot drift from the status every existing query reads.
    st = workflow_stages.describe("hazard_register", row.register_status)
    out.stage = st.get("stage")
    out.stage_number = st.get("stage_number")
    out.stage_label = st.get("stage_label")
    out.completed_stages = st.get("completed_stages") or []
    out.total_stages = st.get("total_stages")

    # Overdue means the containment deadline passed while the hazard is still
    # open. A closed hazard is never overdue, however late it was.
    out.is_overdue = bool(
        row.response_due_at
        and row.register_status in OPEN_STATUSES
        and row.response_due_at < datetime.now()
    )

    if maps:
        people = maps.get("people", {})
        out.logged_by_name = people.get(row.logged_by or 0)
        out.reviewed_by_name = people.get(row.reviewed_by or 0)
        out.control_owner_name = people.get(row.control_owner_id or 0)
        out.assessed_by_name = people.get(row.assessed_by or 0)
        out.interim_control_by_name = people.get(row.interim_control_by or 0)
        out.controls_planned_by_name = people.get(row.controls_planned_by or 0)
        out.controls_verified_by_name = people.get(row.controls_verified_by or 0)
        out.lesson_captured_by_name = people.get(row.lesson_captured_by or 0)
        out.closed_by_name = people.get(row.closed_by or 0)
        out.auditor_verified_by_name = people.get(row.auditor_verified_by or 0)
        out.station_name = maps.get("stations", {}).get(row.location_station_id or 0)
        out.category_name = maps.get("categories", {}).get(row.category_id or 0)
    out.evidence = row.evidence_json or []
    return out


def _respond_one(db: Session, row: Hazard) -> HazardRegisterResponse:
    return _respond(row, _lookup_maps(db, [row]))


def _respond_many(db: Session, rows: Sequence[Hazard]) -> List[HazardRegisterResponse]:
    maps = _lookup_maps(db, rows)
    return [_respond(r, maps) for r in rows]


def _resolve_category_id(db: Session, given: Optional[int], org_id: Optional[int]) -> Optional[int]:
    """hazards.category_id is NOT NULL, but a worker logging a field hazard may not
    pick one — fall back to any category in the org so the log still succeeds.

    A supplied id is also checked against the caller's org before it is trusted.
    The mobile forms shipped with the category list hard-coded to ids 1-10,
    which are organisation 1's rows; every other tenant's worker was filing
    hazards against another organisation's category. The names are seeded
    identically so the label looked right, which is what kept it hidden — but
    the id was foreign, and _is_recurring() groups on category_id, so hazards
    were being counted against the wrong population. An id from outside the org
    is remapped to the org's own category of the same name.
    """
    if given:
        row = db.execute(
            text("SELECT id, category_name, organisation_id FROM hazard_categories WHERE id = :id"),
            {"id": given},
        ).mappings().first()
        if row is None:
            given = None
        elif row["organisation_id"] in (None, org_id):
            return given
        else:
            mine = db.execute(
                text(
                    "SELECT id FROM hazard_categories "
                    "WHERE category_name = :name AND organisation_id = :org LIMIT 1"
                ),
                {"name": row["category_name"], "org": org_id},
            ).mappings().first()
            # No same-named category in this org: fall through to the default
            # rather than store another tenant's row.
            if mine:
                return mine["id"]
            given = None
    if given:
        return given
    row = db.execute(
        text(
            "SELECT id FROM hazard_categories "
            "WHERE organisation_id = :org OR organisation_id IS NULL "
            "ORDER BY (organisation_id = :org) DESC LIMIT 1"
        ),
        {"org": org_id},
    ).mappings().first()
    if row:
        return row["id"]
    row = db.execute(text("SELECT id FROM hazard_categories LIMIT 1")).mappings().first()
    return row["id"] if row else None


def _stamp_review(db: Session, row: Hazard, user: CurrentUser) -> int:
    """Every stage verb touches the reviewer columns — they are the register's
    'who last acted' pair and the auditor list sorts on them."""
    emp = employee_id_for(db, user.user_id)
    row.reviewed_by = emp
    row.reviewed_at = datetime.now()
    return emp


# ══════════════════════════════════════════════════════════════════════════════
# 01 RECORD — log (worker / supervisor)
# ══════════════════════════════════════════════════════════════════════════════
@router.post("/log", response_model=HazardRegisterResponse, status_code=201)
async def log_hazard_http(
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Log a hazard, with or without photos and video attached.

    Takes the raw request rather than a declared `HazardLog` body so the
    multipart shape is accepted — the app switches to multipart the moment a
    file is attached, and against a declared model FastAPI answers 422, which
    fails the whole submission rather than just losing the file. The four
    report workflows already work this way; the register did not, which is why
    its form had no camera button to begin with.

    Validation is not lost, only moved: the same schema is applied here and a
    bad body still comes back as a 422 with Pydantic's own errors.
    """
    data, media_urls = await report_media.read_report_body(request, subdir="hazards")
    data = report_media.merge_media(data, media_urls)
    try:
        payload = HazardLog(**data)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=json.loads(exc.json()))
    return log_hazard(payload, db, current_user)


def log_hazard(
    payload: HazardLog,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    now = datetime.now()
    data = payload.model_dump()
    typed_location = (data.get("location") or "").strip()
    station_id = data.get("location_station_id") or station_id_for(
        db, typed_location, current_user.org_id
    )
    row = Hazard(
        organisation_id=current_user.org_id,
        category_id=_resolve_category_id(db, data.get("category_id"), current_user.org_id),
        hazard_name=data.get("hazard_name"),
        severity=data.get("severity"),
        probability=data.get("probability"),
        # The same two values again, in columns nothing downstream writes to.
        # Stage 02 rescores severity/probability in place, so without this the
        # reporter's answer does not survive their supervisor opening it.
        reported_severity=data.get("severity"),
        reported_probability=data.get("probability"),
        description=data.get("description"),
        location_station_id=station_id,
        # Kept only when what the worker typed matched no station. Storing it
        # either way would put the same place in two columns and leave whoever
        # reads the hazard to guess which one is authoritative.
        location_other=typed_location if typed_location and not station_id else None,
        still_present=(
            None if data.get("still_present") is None else int(bool(data.get("still_present")))
        ),
        controls=data.get("controls"),
        # `controls` is overwritten by /plan-controls with the planned measure.
        # This keeps what the reporter said is already protecting people.
        existing_controls=data.get("controls"),
        persons_exposed=data.get("persons_exposed"),
        # Also revised in place, by /assess and again by /findings.
        reported_persons_exposed=data.get("persons_exposed"),
        gps_latitude=data.get("gps_latitude"),
        gps_longitude=data.get("gps_longitude"),
        evidence_json=data.get("photos"),
        register_status="open",
        logged_by=employee_id_for(db, current_user.user_id),
        logged_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    # A -> B. A hazard reported where an approved assessment already covers the
    # work is evidence that assessment missed something. Flagged rather than
    # reopened: its controls are still in force and the permits under it still
    # stand — what has changed is that somebody has to look.
    covering = risk_assessment_svc.covering_assessment(
        db, current_user.org_id, station_id=row.location_station_id
    )
    if covering is not None:
        risk_assessment_svc.flag_for_review(
            db, covering,
            f"Unsafe act HAZ-{row.id} reported in this area: {row.hazard_name or 'unnamed'}",
        )

    return _respond_one(db, row)


@router.get("/categories")
def list_categories(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """The caller's own hazard categories, for the report forms' dropdown.

    The forms used to carry the list hard-coded with ids 1-10 — organisation 1's
    rows — so every other tenant's worker picked a label from one org and filed
    against another. Serving the list is the only way the id a worker sends can
    be the id their organisation actually uses.

    Global rows (organisation_id IS NULL) are included so a tenant with no
    categories of its own still gets a usable list.
    """
    rows = db.execute(
        text(
            "SELECT id, category_name FROM hazard_categories "
            "WHERE organisation_id = :org OR organisation_id IS NULL "
            "ORDER BY (organisation_id = :org) DESC, id"
        ),
        {"org": current_user.org_id},
    ).mappings().all()
    return [{"id": r["id"], "category_name": r["category_name"]} for r in rows]


@router.get("", response_model=List[HazardRegisterResponse])
@router.get("/", response_model=List[HazardRegisterResponse])
def list_register(
    skip: int = 0,
    limit: int = Query(100, le=500),
    register_status: Optional[str] = None,
    stage: Optional[str] = Query(None, description="RECORD..CLOSE"),
    open_only: bool = Query(False, description="Everything not yet closed"),
    q: Optional[str] = Query(None, description="Match on unsafe act name or description"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    query = db.query(Hazard).filter(Hazard.organisation_id == current_user.org_id)
    # Scoped to the logger's department — the register uses logged_by where
    # the report families use reported_by, but the rule is the same.
    query = department_scope.apply_scope(query, Hazard, "logged_by", db, current_user)
    if register_status:
        query = query.filter(Hazard.register_status == register_status)
    if open_only:
        query = query.filter(Hazard.register_status.in_(OPEN_STATUSES))
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(Hazard.hazard_name.like(like) | Hazard.description.like(like))
    if stage:
        # Filtering by stage means filtering by every status that maps to it —
        # translated here rather than in SQL so the mapping stays in one place.
        wanted = stage.strip().upper()
        statuses = [
            s for s, key in workflow_stages.HAZARD_REGISTER_STATUS_STAGE.items()
            if key == wanted
        ]
        if not statuses:
            raise HTTPException(status_code=400, detail=f"Unknown stage '{stage}'")
        query = query.filter(Hazard.register_status.in_(statuses))

    rows = query.order_by(Hazard.id.desc()).offset(skip).limit(limit).all()
    return _respond_many(db, rows)


@router.get("/my-logs", response_model=List[HazardRegisterResponse])
def my_logs(
    skip: int = 0,
    limit: int = Query(50, le=1000),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    emp_id = employee_id_for(db, current_user.user_id)
    rows = (
        db.query(Hazard)
        .filter(Hazard.organisation_id == current_user.org_id)
        .filter(Hazard.logged_by == emp_id)
        .order_by(Hazard.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return _respond_many(db, rows)


# ══════════════════════════════════════════════════════════════════════════════
# "What is waiting on me"
#
# Declared before /{hazard_id} — FastAPI matches in definition order, and a path
# parameter route registered first would swallow every one of these.
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/next-actions")
def next_actions(
    mine_only: bool = Query(True),
    limit: int = Query(100, le=300),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Every open hazard waiting on this user, with the exact step it needs.

    The register's half of the unified queue. Ordered by assessed priority then
    deadline, so a P1 hazard with no interim control outranks a P4 awaiting a
    lesson — the same ordering the incident queue uses.
    """
    rows = (
        db.query(Hazard)
        .filter(Hazard.organisation_id == current_user.org_id)
        .filter(Hazard.register_status.in_(OPEN_STATUSES + ["controlled"]))
        .order_by(Hazard.id.desc())
        .limit(limit * 3)
        .all()
    )
    maps = _lookup_maps(db, rows)

    # Who this caller is, so a hazard they have already worked stays in their
    # list once the step moves on — the same reason the incident and report
    # queues carry this. The register stamps a different column at each step,
    # so any of the three means "this was mine".
    my_employee_id = db.execute(
        text("SELECT employee_id FROM users WHERE id = :uid"), {"uid": current_user.user_id}
    ).scalar()

    items = []
    mine = 0
    for row in rows:
        desc = hazard_next_action.describe(row.register_status, current_user.role)
        if not desc.get("next_action"):
            continue
        if desc.get("is_mine"):
            mine += 1
        if mine_only and not desc.get("can_act"):
            continue
        na = desc["next_action"]
        items.append({
            "family": "hazard_register",
            "id": row.id,
            "reference": f"HAZ-{row.id}",
            "description": (row.hazard_name or row.description or "")[:140],
            "priority": row.assessed_priority,
            "severity_label": row.assessed_label,
            "register_status": row.register_status,
            "stage": desc.get("stage"),
            "stage_number": desc.get("stage_number"),
            "stage_label": desc.get("stage_label"),
            "action": na["action"],
            "detail": na["detail"],
            "cta": na["cta"],
            "route": na["route"],
            "unblocks": na["unblocks"],
            "owner_role": na["owner_role"],
            "is_mine": desc.get("is_mine"),
            "can_act": desc.get("can_act"),
            "handled_by_me": bool(
                my_employee_id
                and my_employee_id in (row.reviewed_by, row.assessed_by, row.controls_planned_by)
            ),
            "due_at": row.response_due_at.isoformat() if row.response_due_at else None,
            "is_overdue": bool(
                row.response_due_at and row.response_due_at < datetime.now()
            ),
            "work_stopped": bool(row.work_stopped),
            "station_name": maps["stations"].get(row.location_station_id or 0),
            "waiting_since": row.reviewed_at.isoformat() if row.reviewed_at
            else (row.logged_at.isoformat() if row.logged_at else None),
        })

    # Unassessed hazards sort last — they are not "low priority", they are "not
    # yet triaged", and burying them at the top would be worse than showing them
    # at the bottom flagged as such.
    items.sort(key=lambda r: (r["priority"] is None, r["priority"] or "", r["due_at"] or "9999"))
    return {"count": len(items[:limit]), "items": items[:limit], "mine_count": mine}


@router.get("/audit-list", response_model=List[HazardRegisterResponse])
def auditor_audit_list(
    skip: int = 0,
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Hazards still being managed, which the auditor checks on site."""
    require_role(current_user.role, AUDITOR_ROLES | MANAGER_ROLES, "audit hazards")
    rows = (
        db.query(Hazard)
        .filter(Hazard.organisation_id == current_user.org_id)
        .filter(Hazard.register_status.in_(OPEN_STATUSES))
        .order_by(Hazard.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return _respond_many(db, rows)


@router.get("/stats/summary")
def register_stats(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    rows = (
        db.query(Hazard.register_status, Hazard.assessed_priority, Hazard.response_due_at)
        .filter(Hazard.organisation_id == current_user.org_id)
        .all()
    )
    counts: Dict[str, int] = {}
    by_stage = {s.key: 0 for s in workflow_stages.STAGES}
    by_priority: Dict[str, int] = {}
    overdue = 0
    now = datetime.now()

    for register_status, priority, due_at in rows:
        counts[register_status or "unknown"] = counts.get(register_status or "unknown", 0) + 1
        stage = workflow_stages.stage_for("hazard_register", register_status)
        if stage:
            by_stage[stage] += 1
        if priority:
            by_priority[priority] = by_priority.get(priority, 0) + 1
        if due_at and due_at < now and register_status in OPEN_STATUSES:
            overdue += 1

    return {
        "total": len(rows),
        "by_status": counts,
        "by_stage": by_stage,
        "by_priority": by_priority,
        "open": sum(counts.get(s, 0) for s in OPEN_STATUSES),
        "overdue": overdue,
    }


@router.get("/{hazard_id}", response_model=HazardRegisterResponse)
def get_hazard(
    hazard_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    return _respond_one(db, _get(db, hazard_id, current_user.org_id))


@router.get("/{hazard_id}/next-action", response_model=HazardNextActionResponse)
def hazard_next_action_detail(
    hazard_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Stage tracker + outstanding step for one unsafe act."""
    row = _get(db, hazard_id, current_user.org_id)
    desc = hazard_next_action.describe(row.register_status, current_user.role)
    return HazardNextActionResponse(
        hazard_id=row.id,
        reference=f"HAZ-{row.id}",
        track=hazard_next_action.stage_track(row.register_status),
        **desc,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 02 ASSESS
# ══════════════════════════════════════════════════════════════════════════════
@router.post("/{hazard_id}/assess", response_model=HazardRegisterResponse)
def assess_hazard(
    hazard_id: int,
    payload: HazardAssess,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Stage 02 — score the hazard and decide whether the job stops.

    Where it goes next is the assessment's own output, not a separate choice: a
    hazard that stopped the job, or that scores P1/P2, owes containment before
    anything else and moves to RESPOND. Anything lower goes straight to the
    control review, and RESPOND shows as skipped on the trail — which is the
    honest record, because nothing was contained.
    """
    require_role(current_user.role, ALL_ELEVATED_ROLES, "assess hazards")
    row = _get(db, hazard_id, current_user.org_id)
    _require_stage(row, ("open",), "assess this hazard")

    if payload.severity is not None:
        row.severity = payload.severity
    if payload.probability is not None:
        row.probability = payload.probability
    if payload.persons_exposed is not None:
        row.persons_exposed = payload.persons_exposed
    row.work_stopped = int(bool(payload.work_stopped))

    assessment = event_assessment.assess_hazard_register(db, row)
    event_assessment.apply_to_hazard_register(row, assessment)
    row.assessed_by = _stamp_review(db, row, current_user)

    if payload.assessment_notes:
        row.review_notes = payload.assessment_notes

    needs_containment = bool(payload.work_stopped) or row.assessed_priority in ("P1", "P2")
    row.register_status = "interim_control" if needs_containment else "under_review"
    if row.register_status == "under_review":
        row.review_started_at = datetime.now()

    db.commit()
    db.refresh(row)
    return _respond_one(db, row)


# ══════════════════════════════════════════════════════════════════════════════
# 03 RESPOND
# ══════════════════════════════════════════════════════════════════════════════
@router.post("/{hazard_id}/interim-control", response_model=HazardRegisterResponse)
def record_interim_control(
    hazard_id: int,
    payload: HazardInterimControl,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Stage 03 — record the temporary measure holding the hazard.

    Allowed from `open` as well as `interim_control`: a supervisor who walks up
    to a live hazard barriers it off first and does the paperwork afterwards,
    and refusing the record because triage had not been done yet would lose the
    one fact worth capturing.
    """
    require_role(current_user.role, ALL_ELEVATED_ROLES, "record interim controls")
    row = _get(db, hazard_id, current_user.org_id)
    _require_stage(row, ("open", "interim_control", "under_review"), "record an interim control")

    row.interim_control = payload.interim_control
    row.interim_control_by = employee_id_for(db, current_user.user_id)
    row.interim_control_at = datetime.now()
    if payload.work_stopped is not None:
        row.work_stopped = int(payload.work_stopped)
    _stamp_review(db, row, current_user)

    # An interim control on a hazard already under review does not drag it back
    # a stage — the review is the more advanced work and stands.
    if row.register_status != "under_review":
        row.register_status = "interim_control"

    db.commit()
    db.refresh(row)
    return _respond_one(db, row)


# ══════════════════════════════════════════════════════════════════════════════
# 04 INVESTIGATE
# ══════════════════════════════════════════════════════════════════════════════
@router.post("/{hazard_id}/start-review", response_model=HazardRegisterResponse)
def start_review(
    hazard_id: int,
    payload: HazardStartReview,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Stage 04 — open the control review.

    Separate from submitting findings so the hazard is visibly *in* INVESTIGATE
    while the work happens, rather than appearing to jump from a barrier tape to
    a finished root cause.
    """
    require_role(current_user.role, ALL_ELEVATED_ROLES, "review hazards")
    row = _get(db, hazard_id, current_user.org_id)
    _require_stage(row, ("open", "interim_control"), "start the control review")

    row.register_status = "under_review"
    row.review_started_at = datetime.now()
    if payload.review_notes:
        row.review_notes = payload.review_notes
    _stamp_review(db, row, current_user)

    db.commit()
    db.refresh(row)
    return _respond_one(db, row)


@router.post("/{hazard_id}/findings", response_model=HazardRegisterResponse)
def record_findings(
    hazard_id: int,
    payload: HazardReviewFindings,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Stage 04 — why the hazard exists. Does not advance the stage on its own;
    planning the control is what moves it to IMPROVE."""
    require_role(current_user.role, ALL_ELEVATED_ROLES, "record review findings")
    row = _get(db, hazard_id, current_user.org_id)
    _require_stage(row, ("under_review",), "record review findings")

    if payload.root_cause is not None:
        row.root_cause = payload.root_cause
    if payload.review_notes is not None:
        row.review_notes = payload.review_notes
    if payload.persons_exposed is not None:
        row.persons_exposed = payload.persons_exposed
    _stamp_review(db, row, current_user)

    db.commit()
    db.refresh(row)
    return _respond_one(db, row)


# ══════════════════════════════════════════════════════════════════════════════
# 05 IMPROVE
# ══════════════════════════════════════════════════════════════════════════════
@router.post("/{hazard_id}/plan-controls", response_model=HazardRegisterResponse)
def plan_controls(
    hazard_id: int,
    payload: HazardPlanControls,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Stage 05 — specify the permanent control at its level in the hierarchy.

    PPE is accepted but must be justified. It is the weakest control and the
    only one that protects a person rather than removing the hazard, so a
    register full of unexplained PPE answers is the signal this stage exists to
    surface.
    """
    require_role(current_user.role, ALL_ELEVATED_ROLES, "plan hazard controls")
    row = _get(db, hazard_id, current_user.org_id)
    _require_stage(
        row,
        ("under_review", "interim_control", "controls_planned"),
        "plan controls",
    )

    hierarchy = (payload.control_hierarchy or "").strip().lower()
    if hierarchy not in HIERARCHY:
        raise HTTPException(
            status_code=400,
            detail=f"control_hierarchy must be one of: {', '.join(HIERARCHY)}",
        )
    if hierarchy == "ppe" and not (payload.ppe_justification or "").strip():
        raise HTTPException(
            status_code=400,
            detail=(
                "PPE is the weakest control. State why elimination, substitution, "
                "engineering or administrative controls are not reasonably practicable."
            ),
        )

    if payload.control_owner_id:
        owner_in_org = db.execute(
            text("SELECT id FROM employees WHERE id = :id AND organisation_id = :org_id"),
            {"id": payload.control_owner_id, "org_id": current_user.org_id},
        ).scalar()
        if not owner_in_org:
            raise HTTPException(status_code=404, detail="No such employee")

    row.planned_controls = payload.planned_controls
    row.control_hierarchy = hierarchy
    row.control_owner_id = payload.control_owner_id
    row.control_due_date = payload.control_due_date
    row.controls_planned_by = employee_id_for(db, current_user.user_id)
    row.controls_planned_at = datetime.now()
    # `controls` is what the website's register list has always rendered — keep
    # it in step so the catalog view does not go blank for hazards planned here.
    row.controls = payload.planned_controls
    if hierarchy == "ppe":
        row.review_notes = f"PPE justification: {payload.ppe_justification.strip()}"
    row.register_status = "controls_planned"
    _stamp_review(db, row, current_user)

    db.commit()
    db.refresh(row)
    return _respond_one(db, row)


@router.post("/{hazard_id}/submit-verification", response_model=HazardRegisterResponse)
def submit_for_verification(
    hazard_id: int,
    payload: HazardSubmitVerification,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Stage 05 → 06 — the planned control is now actually in place."""
    require_role(current_user.role, ALL_ELEVATED_ROLES, "submit hazard controls")
    row = _get(db, hazard_id, current_user.org_id)
    _require_stage(row, ("controls_planned",), "submit the control for verification")

    if not (row.planned_controls or "").strip():
        raise HTTPException(
            status_code=400,
            detail="No control has been planned for this unsafe act yet.",
        )

    row.register_status = "pending_verification"
    if payload.implementation_notes:
        row.control_verification_notes = payload.implementation_notes
    _stamp_review(db, row, current_user)

    db.commit()
    db.refresh(row)
    return _respond_one(db, row)


# ══════════════════════════════════════════════════════════════════════════════
# 06 VERIFY
# ══════════════════════════════════════════════════════════════════════════════
@router.post("/{hazard_id}/verify-controls", response_model=HazardRegisterResponse)
def verify_controls(
    hazard_id: int,
    payload: HazardVerifyControls,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Stage 06 VERIFY — did the permanent control actually work?

    Answering no returns the hazard to IMPROVE and counts the failure. A control
    that did not hold means the hazard is still live, and marking it
    `controlled` on the strength of a plan rather than a check is exactly what
    this stage prevents.
    """
    require_role(current_user.role, MANAGER_ROLES, "verify hazard controls")
    row = _get(db, hazard_id, current_user.org_id)
    _require_stage(
        row,
        ("pending_verification", "controls_planned"),
        "verify the control",
    )

    from_status = row.register_status
    row.register_status = "controlled" if payload.effective else "controls_planned"
    verifier_id = employee_id_for(db, current_user.user_id)
    row.controls_verified_by = verifier_id
    row.controls_verified_at = datetime.now()
    if payload.verification_notes is not None:
        row.control_verification_notes = payload.verification_notes
    if not payload.effective:
        row.verification_failures = (row.verification_failures or 0) + 1
    _stamp_review(db, row, current_user)
    record_audit(db, current_user.org_id, verifier_id, "verify_controls", "hazard_register", row.id, from_status, row.register_status)

    db.commit()
    db.refresh(row)
    return _respond_one(db, row)


# ══════════════════════════════════════════════════════════════════════════════
# 07 LEARN
# ══════════════════════════════════════════════════════════════════════════════
@router.post("/{hazard_id}/lesson", response_model=HazardRegisterResponse)
def capture_lesson(
    hazard_id: int,
    payload: HazardLesson,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Stage 07 — what the register learned. Recorded before closure.

    Does not advance the status: LEARN and the `controlled` state are the same
    position, and closing is the separate act that ends the lifecycle.
    """
    require_role(current_user.role, ALL_ELEVATED_ROLES, "record hazard lessons")
    row = _get(db, hazard_id, current_user.org_id)
    _require_stage(row, ("controlled",), "capture the lesson")

    row.lessons_learned = payload.lessons_learned
    row.lesson_captured_by = employee_id_for(db, current_user.user_id)
    row.lesson_captured_at = datetime.now()
    _stamp_review(db, row, current_user)

    db.commit()
    db.refresh(row)
    return _respond_one(db, row)


# ══════════════════════════════════════════════════════════════════════════════
# 08 CLOSE
# ══════════════════════════════════════════════════════════════════════════════
@router.post("/{hazard_id}/close", response_model=HazardRegisterResponse)
def close_hazard(
    hazard_id: int,
    payload: Optional[HazardClose] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Stage 08 CLOSE.

    Only from LEARN. Closing a hazard whose control was never verified is the
    failure this gate exists to prevent — the register would then claim a
    hazard is dealt with on the strength of a plan.
    """
    # WF-01 Flow A step 07: "CLOSES IT — Only this role can close a hazard on
    # the register." The Safety Manager owns the register, and closing is the
    # act of saying the site is no longer carrying that hazard. A supervisor
    # can control one and confirm the control is holding; signing it off the
    # register is somebody else's call, which is the whole point of the split.
    require_role(current_user.role, MANAGER_ROLES, "close hazards on the register")
    row = _get(db, hazard_id, current_user.org_id)

    if row.register_status == "closed":
        raise HTTPException(status_code=400, detail="Unsafe act is already closed")
    if row.register_status != "controlled":
        st = workflow_stages.describe("hazard_register", row.register_status)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Hazard is at stage {st.get('stage_number')} "
                f"{st.get('stage_label') or row.register_status} and cannot be closed yet. "
                "Its controls must be planned and verified effective first."
            ),
        )

    now = datetime.now()
    emp = employee_id_for(db, current_user.user_id)
    if payload:
        if payload.closure_notes is not None:
            row.closure_notes = payload.closure_notes
        # Accepted here so LEARN and CLOSE can be one action for a manager who
        # is writing the lesson at the moment of closing.
        if payload.lessons_learned:
            row.lessons_learned = payload.lessons_learned
            row.lesson_captured_by = emp
            row.lesson_captured_at = now

    row.register_status = "closed"
    row.closed_by = emp
    row.closed_at = now
    _stamp_review(db, row, current_user)
    record_audit(db, current_user.org_id, emp, "close", "hazard_register", row.id, "controlled", "closed")

    db.commit()
    db.refresh(row)
    return _respond_one(db, row)


# ══════════════════════════════════════════════════════════════════════════════
# Generic review — the pre-stage escape hatch
# ══════════════════════════════════════════════════════════════════════════════
@router.post("/{hazard_id}/review", response_model=HazardRegisterResponse)
def review_hazard(
    hazard_id: int,
    payload: HazardReview,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Set status, notes, controls or severity directly.

    Retained for the clients that already post to it. The stage verbs above
    record who did what at which stage; this one cannot, so a hazard driven
    entirely through here will have a sparse trail.
    """
    require_role(current_user.role, ALL_ELEVATED_ROLES, "review hazards")
    row = _get(db, hazard_id, current_user.org_id)
    if payload.register_status is not None:
        if payload.register_status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status '{payload.register_status}'")
        row.register_status = payload.register_status
    if payload.review_notes is not None:
        row.review_notes = payload.review_notes
    if payload.controls is not None:
        row.controls = payload.controls
    if payload.severity is not None:
        row.severity = payload.severity
    _stamp_review(db, row, current_user)
    db.commit()
    db.refresh(row)
    return _respond_one(db, row)


# ══════════════════════════════════════════════════════════════════════════════
# Auditor — post-closure assurance, gates nothing
# ══════════════════════════════════════════════════════════════════════════════
@router.post("/{hazard_id}/verify", response_model=HazardRegisterResponse)
def auditor_verify(
    hazard_id: int,
    payload: HazardVerify,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, AUDITOR_ROLES | MANAGER_ROLES, "verify hazards")
    row = _get(db, hazard_id, current_user.org_id)
    row.auditor_verified_by = employee_id_for(db, current_user.user_id)
    row.auditor_verified_at = datetime.now()
    if payload.verification_notes is not None:
        row.verification_notes = payload.verification_notes
    db.commit()
    db.refresh(row)
    return _respond_one(db, row)
