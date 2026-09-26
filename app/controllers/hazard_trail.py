"""Hazard register lifecycle tracking — every action from log to closure.

The register's twin of `/incident-trail`, and deliberately the same response
shape: the web console renders one lifecycle component, and a second shape would
mean a second renderer that drifts from the first.

The trail is reconstructed from the workflow timestamp columns migration 066
added, not from `audit_logs` — nothing writes to that table yet. A column with
a timestamp of its own is reported as fact; a column without one (a root cause,
a set of review notes) is anchored to the step that must have carried it and
flagged `timestamp_inferred`, so the admin can tell what was recorded from what
was deduced.
"""
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import CurrentUser, get_current_user
from app.services import workflow_stages
from app.services.workflow_stages import (
    ASSESS,
    CLOSE,
    IMPROVE,
    INVESTIGATE,
    LEARN,
    RECORD,
    RESPOND,
    VERIFY,
)

# Mounted twice by main.py — see the note in hazard_register.py.
router = APIRouter(tags=["Unsafe Act Register"])

FAMILY = "hazard_register"

# ── Timestamped actions: (column, stage, label, actor column) ────────────────
#
# In lifecycle order. Each row here is something the register can prove
# happened, because a person and a moment were both recorded against it.
_TIMELINE = [
    ("logged_at", RECORD, "Unsafe act logged", "logged_by"),
    ("assessed_at", ASSESS, "Unsafe act assessed", "assessed_by"),
    ("interim_control_at", RESPOND, "Interim control applied", "interim_control_by"),
    ("review_started_at", INVESTIGATE, "Control review opened", "reviewed_by"),
    ("controls_planned_at", IMPROVE, "Permanent control planned", "controls_planned_by"),
    ("controls_verified_at", VERIFY, "Control verified", "controls_verified_by"),
    ("lesson_captured_at", LEARN, "Lesson captured", "lesson_captured_by"),
    ("closed_at", CLOSE, "Unsafe act closed", "closed_by"),
    # Post-closure assurance. Filed under CLOSE because that is when it happens,
    # but it gates nothing — the auditor observes the chain, they do not drive it.
    ("auditor_verified_at", CLOSE, "Auditor verified on site", "auditor_verified_by"),
]

# The detail column that belongs with each timestamped action.
_DETAIL_FOR = {
    "logged_at": "description",
    "assessed_at": "assessed_label",
    "interim_control_at": "interim_control",
    "controls_planned_at": "planned_controls",
    "controls_verified_at": "control_verification_notes",
    "lesson_captured_at": "lessons_learned",
    "closed_at": "closure_notes",
    "auditor_verified_at": "verification_notes",
}

# ── Untimed columns: (column, stage, label, anchor candidates) ───────────────
#
# These carry real content but no timestamp of their own. Anchoring is the only
# honest option — dropping them would hide the root cause entirely, and inventing
# a time would put a fabricated moment in an audit record.
_UNTIMED = [
    ("root_cause", INVESTIGATE, "Root cause established",
     ("review_started_at", "controls_planned_at", "reviewed_at")),
    ("review_notes", INVESTIGATE, "Review note recorded",
     ("review_started_at", "reviewed_at", "assessed_at")),
    ("controls", IMPROVE, "Control recorded on the register",
     ("controls_planned_at", "reviewed_at")),
]


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def _hazard_row(db: Session, hazard_id: int, org_id: Optional[int]) -> dict:
    row = db.execute(
        text("SELECT * FROM hazards WHERE id = :id"), {"id": hazard_id}
    ).mappings().first()
    if not row or (org_id is not None and row["organisation_id"] not in (None, org_id)):
        raise HTTPException(status_code=404, detail="Unsafe act not found")
    return dict(row)


def _fetch_people(db: Session, employee_ids: set) -> Dict[int, dict]:
    """employees.id -> the identifying record the admin needs. One query.

    Same joins as `incident_trail._fetch_people`, and for the same reasons:
    there is no `job_role` column on `employees` (the role is `roles.role_name`
    via `role_id`), and only `users` bridges an employee id to the login account
    an admin chasing "who did this" actually needs.
    """
    ids = sorted({int(i) for i in employee_ids if i})
    if not ids:
        return {}
    rows = db.execute(
        text(
            "SELECT e.id, e.full_name, e.employment_type, e.active_status, "
            "       r.role_name, d.department_name, u.username, u.email "
            "  FROM employees e "
            "  LEFT JOIN roles r ON r.id = e.role_id "
            "  LEFT JOIN departments d ON d.id = e.department_id "
            "  LEFT JOIN users u ON u.employee_id = e.id "
            " WHERE e.id IN :ids"
        ),
        {"ids": tuple(ids)},
    ).mappings().all()
    return {
        r["id"]: {
            "name": r["full_name"],
            "job_role": r["role_name"],
            "department": r["department_name"],
            "employment_type": r["employment_type"],
            "is_active": (r["active_status"] or "").strip().lower() == "active",
            "username": r["username"],
            "email": r["email"],
        }
        for r in rows
    }


def _build_actions(hz: dict) -> List[dict]:
    """Every recorded action on one hazard, oldest first."""
    actions: List[dict] = []

    for column, stage, label, actor_col in _TIMELINE:
        when = hz.get(column)
        if not when:
            continue
        detail = hz.get(_DETAIL_FOR.get(column) or "")
        actions.append({
            "stage": stage,
            "action": label,
            "detail": (str(detail)[:400] if detail else None),
            "actor_id": hz.get(actor_col) if actor_col else None,
            "occurred_at": when,
            "source": f"hazards.{column}",
            "timestamp_inferred": False,
            "reference": None,
        })

    for column, stage, label, anchors in _UNTIMED:
        value = hz.get(column)
        if not value:
            continue
        anchor_at, anchor_col = None, None
        for candidate in anchors:
            if hz.get(candidate):
                anchor_at, anchor_col = hz[candidate], candidate
                break
        if not anchor_at:
            continue  # nothing to anchor to — the action cannot be placed in time
        actions.append({
            "stage": stage,
            "action": label,
            "detail": str(value)[:400],
            "actor_id": hz.get("reviewed_by"),
            "occurred_at": anchor_at,
            "source": f"hazards.{column}",
            "timestamp_inferred": True,
            "inferred_from": f"hazards.{anchor_col}",
            "reference": None,
        })

    # A failed verification is a real event the columns record only as a count.
    # Reported as one line rather than n, because the register keeps the tally
    # and not the individual dates.
    failures = hz.get("verification_failures") or 0
    if failures:
        actions.append({
            "stage": VERIFY,
            "action": f"Control failed verification ({failures}×)",
            "detail": "The control did not hold and the unsafe act returned to IMPROVE.",
            "actor_id": hz.get("controls_verified_by"),
            "occurred_at": hz.get("controls_verified_at") or hz.get("reviewed_at"),
            "source": "hazards.verification_failures",
            "timestamp_inferred": True,
            "inferred_from": "hazards.controls_verified_at",
            "reference": None,
        })

    # Stage number breaks the tie, not insertion order. An anchored action
    # borrows the timestamp of the column it hangs off, so "root cause
    # established" ties with "control review opened" to the second and, sorted
    # on time alone, lands wherever it happened to be appended -- which is after
    # every timestamped row, so the trail read "hazard closed" before "root
    # cause established". Ordering ties by stage puts each anchored action back
    # beside the stage it belongs to.
    def _order(a: dict):
        return (
            a["occurred_at"] is None,
            a["occurred_at"] or 0,
            workflow_stages.stage_number(a["stage"]) or 0,
            # An anchored row follows the timestamped row it borrowed from.
            1 if a.get("timestamp_inferred") else 0,
        )

    actions.sort(key=_order)
    for i, a in enumerate(actions, start=1):
        a["sequence"] = i
        a["stage_number"] = workflow_stages.stage_number(a["stage"])
        a["occurred_at"] = _iso(a["occurred_at"])
    return actions


def _build_people(db: Session, hz: dict, actions: List[dict]) -> List[dict]:
    """Who touched this hazard, with the identity an admin needs.

    Built from the actions rather than from a fixed column list, so a person who
    only ever applied an interim control still appears.
    """
    # employee id -> the workflow roles the columns give them
    roles: Dict[int, set] = {}
    for column, label in (
        ("logged_by", "Logged"), ("assessed_by", "Assessor"),
        ("interim_control_by", "Interim control"), ("reviewed_by", "Reviewer"),
        ("control_owner_id", "Control owner"), ("controls_planned_by", "Control planner"),
        ("controls_verified_by", "Verifier"), ("lesson_captured_by", "Lesson author"),
        ("closed_by", "Closed by"), ("auditor_verified_by", "Auditor"),
    ):
        emp = hz.get(column)
        if emp:
            roles.setdefault(int(emp), set()).add(label)

    for a in actions:
        if a["actor_id"]:
            roles.setdefault(int(a["actor_id"]), set())

    records = _fetch_people(db, set(roles))
    people = []
    for emp_id, workflow_roles in roles.items():
        rec = records.get(emp_id)
        own = [a for a in actions if a["actor_id"] == emp_id]
        times = [a["occurred_at"] for a in own if a["occurred_at"]]
        people.append({
            "employee_id": emp_id,
            "employee_ref": f"EMP-{emp_id}",
            "name": rec.get("name") if rec else None,
            "job_role": rec.get("job_role") if rec else None,
            "department": rec.get("department") if rec else None,
            "employment_type": rec.get("employment_type") if rec else None,
            "is_active": rec.get("is_active", True) if rec else False,
            "username": rec.get("username") if rec else None,
            "email": rec.get("email") if rec else None,
            # The hazard names an employee id with no matching employee row.
            "record_missing": rec is None,
            "workflow_roles": sorted(workflow_roles),
            "action_count": len(own),
            "actions": [a["action"] for a in own],
            "first_action_at": min(times) if times else None,
            "last_action_at": max(times) if times else None,
        })
    people.sort(key=lambda p: (p["first_action_at"] or "9999", p["employee_id"]))
    return people


# ══════════════════════════════════════════════════════════════════════════════
# Endpoints
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/stages")
def trail_stages(current_user: CurrentUser = Depends(get_current_user)):
    """The eight stages, for a client rendering the whole lifecycle."""
    return {"stages": workflow_stages.catalogue()}


@router.get("")
@router.get("/")
def list_tracked_hazards(
    stage: Optional[str] = Query(None, description="RECORD..CLOSE"),
    q: Optional[str] = Query(None),
    limit: int = Query(100, le=300),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Every hazard with its current stage and a summary of its trail."""
    where = ["h.organisation_id = :org"]
    params: Dict[str, object] = {"org": current_user.org_id, "lim": limit}
    if q:
        where.append("(h.hazard_name LIKE :q OR h.description LIKE :q)")
        params["q"] = f"%{q.strip()}%"

    # Filtering by stage means filtering by every status that maps to it. Done
    # in SQL rather than after the fetch, because LIMIT applies first — a
    # post-filter on a rare stage would return a nearly empty page while the
    # register held plenty of matches.
    if stage:
        wanted_stage = stage.strip().upper()
        statuses = [
            s for s, key in workflow_stages.HAZARD_REGISTER_STATUS_STAGE.items()
            if key == wanted_stage
        ]
        if not statuses:
            raise HTTPException(status_code=400, detail=f"Unknown stage '{stage}'")
        where.append("h.register_status IN :statuses")
        params["statuses"] = tuple(statuses)

    rows = db.execute(
        text(
            "SELECT h.*, "
            "       lg.full_name AS logged_by_name, rv.full_name AS reviewed_by_name, "
            "       co.full_name AS control_owner_name, ws.station_name, "
            "       hc.category_name "
            "  FROM hazards h "
            "  LEFT JOIN employees lg ON lg.id = h.logged_by "
            "  LEFT JOIN employees rv ON rv.id = h.reviewed_by "
            "  LEFT JOIN employees co ON co.id = h.control_owner_id "
            "  LEFT JOIN working_stations ws ON ws.id = h.location_station_id "
            "  LEFT JOIN hazard_categories hc ON hc.id = h.category_id "
            f" WHERE {' AND '.join(where)} "
            " ORDER BY h.id DESC LIMIT :lim"
        ),
        params,
    ).mappings().all()

    # Counted over the whole register, not over `rows` — those are LIMITed, and
    # the client renders these as the stage filter's totals. Counting the page
    # would make the pills shrink as the user narrowed the list.
    stage_counts = {s.key: 0 for s in workflow_stages.STAGES}
    for r in db.execute(
        text(
            "SELECT register_status, COUNT(*) AS n FROM hazards "
            " WHERE organisation_id = :org GROUP BY register_status"
        ),
        {"org": current_user.org_id},
    ).mappings().all():
        key = workflow_stages.stage_for(FAMILY, r["register_status"])
        if key:
            stage_counts[key] += r["n"]

    items = []
    for r in rows:
        hz = dict(r)
        stage_key = workflow_stages.stage_for(FAMILY, hz.get("register_status"))
        actions = _build_actions(hz)
        last = actions[-1]["occurred_at"] if actions else None
        items.append({
            "id": hz["id"],
            "reference": f"HAZ-{hz['id']}",
            "description": hz.get("hazard_name") or hz.get("description"),
            "hazard_name": hz.get("hazard_name"),
            "category_name": hz.get("category_name"),
            "station_name": hz.get("station_name"),
            "severity": hz.get("severity"),
            "probability": hz.get("probability"),
            "risk_score": hz.get("risk_score"),
            "priority": hz.get("assessed_priority"),
            "severity_label": hz.get("assessed_label"),
            "register_status": hz.get("register_status"),
            "stage": stage_key,
            "stage_number": workflow_stages.stage_number(stage_key),
            "control_hierarchy": hz.get("control_hierarchy"),
            "work_stopped": bool(hz.get("work_stopped")),
            "verification_failures": hz.get("verification_failures") or 0,
            "logged_at": _iso(hz.get("logged_at")),
            "closed_at": _iso(hz.get("closed_at")),
            "response_due_at": _iso(hz.get("response_due_at")),
            "control_due_date": _iso(hz.get("control_due_date")),
            "last_action_at": last,
            "action_count": len(actions),
            "logged_by_id": hz.get("logged_by"),
            "logged_by_name": hz.get("logged_by_name"),
            "reviewed_by_id": hz.get("reviewed_by"),
            "reviewed_by_name": hz.get("reviewed_by_name"),
            "control_owner_id": hz.get("control_owner_id"),
            "control_owner_name": hz.get("control_owner_name"),
            "auditor_verified": bool(hz.get("auditor_verified_at")),
        })

    return {"count": len(items), "items": items, "stage_counts": stage_counts}


@router.get("/{hazard_id}")
def hazard_trail(
    hazard_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """The full action-by-action trail for one hazard, grouped by stage.

    `stages` carries all eight whether or not anything happened in them — a
    stage that was skipped is exactly what the admin is looking for, so it has
    to be visible rather than absent.
    """
    hz = _hazard_row(db, hazard_id, current_user.org_id)
    actions = _build_actions(hz)

    current_stage = workflow_stages.stage_for(FAMILY, hz.get("register_status"))
    current_number = workflow_stages.stage_number(current_stage) or 0

    by_stage: Dict[str, List[dict]] = {}
    for a in actions:
        if a["stage"]:
            by_stage.setdefault(a["stage"], []).append(a)

    stages = []
    for s in workflow_stages.STAGES:
        entries = by_stage.get(s.key, [])
        if s.number < current_number:
            state = "complete" if entries else "skipped"
        elif s.number == current_number:
            # Reaching CLOSE *is* the completion — there is no ninth stage, so
            # the last stage must not read "in progress" on a closed hazard.
            state = "complete" if s.key == CLOSE else "current"
        else:
            state = "pending"
        stages.append({
            "number": s.number,
            "key": s.key,
            "label": s.label,
            "description": s.description,
            "state": state,
            "entered_at": entries[0]["occurred_at"] if entries else None,
            "last_action_at": entries[-1]["occurred_at"] if entries else None,
            "action_count": len(entries),
            "actions": entries,
        })

    return {
        "hazard": {
            "id": hz["id"],
            "reference": f"HAZ-{hz['id']}",
            "hazard_name": hz.get("hazard_name"),
            "description": hz.get("description"),
            "severity": hz.get("severity"),
            "probability": hz.get("probability"),
            "risk_score": hz.get("risk_score"),
            "priority": hz.get("assessed_priority"),
            "severity_label": hz.get("assessed_label"),
            "register_status": hz.get("register_status"),
            "stage": current_stage,
            "stage_number": current_number or None,
            "work_stopped": bool(hz.get("work_stopped")),
            "persons_exposed": hz.get("persons_exposed"),
            "interim_control": hz.get("interim_control"),
            "root_cause": hz.get("root_cause"),
            "planned_controls": hz.get("planned_controls"),
            "control_hierarchy": hz.get("control_hierarchy"),
            "control_due_date": _iso(hz.get("control_due_date")),
            "verification_failures": hz.get("verification_failures") or 0,
            "control_verification_notes": hz.get("control_verification_notes"),
            "lessons_learned": hz.get("lessons_learned"),
            "closure_notes": hz.get("closure_notes"),
            "logged_at": _iso(hz.get("logged_at")),
            "response_due_at": _iso(hz.get("response_due_at")),
            "closed_at": _iso(hz.get("closed_at")),
            "gps_latitude": hz.get("gps_latitude"),
            "gps_longitude": hz.get("gps_longitude"),
        },
        "stages": stages,
        "actions": actions,
        "people": _build_people(db, hz, actions),
        "unstaged_actions": [a for a in actions if not a["stage"]],
        "total_actions": len(actions),
        "total_stages": len(workflow_stages.STAGES),
        "skipped_stages": [s["key"] for s in stages if s["state"] == "skipped"],
    }
