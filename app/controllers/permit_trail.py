"""Permit-to-work lifecycle tracking — every action from request to closure.

The permit twin of `/incident-trail` and `/near-miss-trail`, and deliberately
the same response shape: the web console renders one lifecycle component, and a
second shape would mean a second renderer that drifts from the first.

The trail is reconstructed from the workflow timestamp columns migrations 031,
044 and 058 added, not from `audit_logs` — nothing writes to that table yet. A
column with a timestamp of its own is reported as fact; one without (a
suspension reason, a set of supervisor notes) is anchored to the step that must
have carried it and flagged `timestamp_inferred`, so the admin can tell what was
recorded from what was deduced.

Unlike the report families, the auditor is a real actor in this chain: their
on-site check happens while the permit is live and moves it to `verified`.
"""
import json
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import CurrentUser, get_current_user
from app.services import permit_next_action, workflow_stages
from app.services.workflow_stages import (
    ASSESS, CLOSE, IMPROVE, INVESTIGATE, LEARN, RECORD, RESPOND, VERIFY,
)

router = APIRouter(prefix="/permit-trail", tags=["Permit Trail"])

FAMILY = "permit"
TABLE = "permits_to_work"

# (timestamp column, stage, label, actor column)
_TIMELINE: List[tuple] = [
    ("created_at",          RECORD,      "Permit record created",        "requested_by"),
    ("requested_at",        RECORD,      "Permit requested",             "requested_by"),
    ("acknowledged_at",     ASSESS,      "Acknowledged by supervisor",   "acknowledged_by"),
    ("gate_checked_at",     ASSESS,      "Gate check evaluated",         None),
    ("approved_at",         IMPROVE,     "Permit approved and issued",   "approved_by"),
    ("rejected_at",         CLOSE,       "Permit rejected",              "approved_by"),
    ("work_start_actual",   IMPROVE,     "Work started under the permit", "issued_by"),
    ("auditor_verified_at", VERIFY,      "Controls verified on site",    "auditor_verified_by"),
    ("work_end_actual",     LEARN,       "Work completed",               "issued_by"),
]

_DETAIL_FOR: Dict[str, str] = {
    "acknowledged_at": "supervisor_notes",
    "gate_checked_at": "gate_blocked_reason",
    "rejected_at": "rejection_reason",
    "auditor_verified_at": "verification_notes",
}

# Text columns with no timestamp of their own, anchored to the step that must
# have carried them.
_UNTIMED: List[tuple] = [
    ("gate_blocked_reason", RESPOND, "Gate blocked the permit",
     ("gate_checked_at", "acknowledged_at", "requested_at")),
    ("suspension_reason", INVESTIGATE, "Work suspended",
     ("work_start_actual", "approved_at")),
]

_ACTOR_COLUMNS: Dict[str, str] = {
    "requested_by": "Requester",
    "acknowledged_by": "Acknowledging supervisor",
    "approved_by": "Approving manager",
    "issued_by": "Permit issuer",
    "auditor_verified_by": "Auditor",
}


def _iso(v) -> Optional[str]:
    return v.isoformat() if v else None


def _ref(pid: int) -> str:
    """Matches `_permit_ref` in permit_workflow, so one permit is named the
    same wherever the admin meets it."""
    return f"PTW-{pid:04d}"


def _fetch_people(db: Session, employee_ids: set) -> Dict[int, dict]:
    ids = {int(i) for i in employee_ids if i}
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
            "employee_id": r["id"], "employee_ref": f"EMP-{r['id']}",
            "name": r["full_name"], "job_role": r["role_name"],
            "department": r["department_name"], "employment_type": r["employment_type"],
            "is_active": (r["active_status"] or "").strip().lower() == "active",
            "username": r["username"], "email": r["email"],
        }
        for r in rows
    }


def _row(db: Session, permit_id: int, org_id: Optional[int]) -> dict:
    row = db.execute(
        text(f"SELECT * FROM {TABLE} WHERE id = :id AND organisation_id = :org"),
        {"id": permit_id, "org": org_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Permit {permit_id} not found")
    return dict(row)


def _build_actions(db: Session, p: dict) -> List[dict]:
    """Every recorded action on one permit, in lifecycle order."""
    actions: List[dict] = []

    for column, stage, label, actor_col in _TIMELINE:
        when = p.get(column)
        if not when:
            continue
        detail_col = _DETAIL_FOR.get(column)
        detail = p.get(detail_col) if detail_col else None
        actions.append({
            "stage": stage, "action": label,
            "detail": (str(detail)[:400] if detail else None),
            "actor_id": p.get(actor_col) if actor_col else None,
            "occurred_at": when, "source": f"{TABLE}.{column}",
            "timestamp_inferred": False, "reference": None,
        })

    for column, stage, label, anchors in _UNTIMED:
        value = p.get(column)
        if not value:
            continue
        anchor_at, anchor_col = None, None
        for cand in anchors:
            if p.get(cand):
                anchor_at, anchor_col = p[cand], cand
                break
        if not anchor_at:
            continue
        actions.append({
            "stage": stage, "action": label,
            "detail": (value[:400] if isinstance(value, str) else None),
            "actor_id": None, "occurred_at": anchor_at,
            "source": f"{TABLE}.{column}", "timestamp_inferred": True,
            "inferred_from": f"{TABLE}.{anchor_col}", "reference": None,
        })

    # Stage first, then time — the permit columns are written from the same mix
    # of clocks the incident trail documents, so time alone reads out of order.
    actions.sort(key=lambda a: (
        workflow_stages.stage_number(a["stage"]) or 99,
        a["occurred_at"] is None, a["occurred_at"],
    ))
    directory = _fetch_people(db, {a["actor_id"] for a in actions})
    for i, a in enumerate(actions, 1):
        person = directory.get(a["actor_id"]) if a["actor_id"] else None
        a["sequence"] = i
        a["actor_name"] = person["name"] if person else None
        a["actor_ref"] = f"EMP-{a['actor_id']}" if a["actor_id"] else None
        a["actor_job_role"] = person["job_role"] if person else None
        a["actor_department"] = person["department"] if person else None
        a["actor_username"] = person["username"] if person else None
        a["stage_number"] = workflow_stages.stage_number(a["stage"])
        a["occurred_at"] = _iso(a["occurred_at"])
    return actions


def _build_people(db: Session, p: dict, actions: List[dict]) -> List[dict]:
    roles_by_person: Dict[int, set] = {}
    for column, role in _ACTOR_COLUMNS.items():
        emp = p.get(column)
        if emp:
            roles_by_person.setdefault(int(emp), set()).add(role)
    acted: Dict[int, List[dict]] = {}
    for a in actions:
        if a.get("actor_id"):
            acted.setdefault(int(a["actor_id"]), []).append(a)

    everyone = set(roles_by_person) | set(acted)
    directory = _fetch_people(db, everyone)
    people = []
    for emp_id in everyone:
        entries = acted.get(emp_id, [])
        times = [e["occurred_at"] for e in entries if e["occurred_at"]]
        person = directory.get(emp_id) or {
            "employee_id": emp_id, "employee_ref": f"EMP-{emp_id}", "name": None,
            "job_role": None, "department": None, "employment_type": None,
            "is_active": False, "username": None, "email": None,
        }
        people.append({
            **person, "record_missing": emp_id not in directory,
            "workflow_roles": sorted(roles_by_person.get(emp_id, set())),
            "action_count": len(entries), "actions": [e["action"] for e in entries],
            "first_action_at": min(times) if times else None,
            "last_action_at": max(times) if times else None,
        })
    people.sort(key=lambda x: (-x["action_count"], x["name"] or "", x["employee_id"]))
    return people


def _chronology_warnings(actions: List[dict]) -> List[dict]:
    warnings, hw, hw_action = [], None, None
    for a in actions:
        if not a["occurred_at"] or a["stage_number"] is None:
            continue
        if hw and a["occurred_at"] < hw:
            warnings.append({
                "action": a["action"], "stage": a["stage"],
                "occurred_at": a["occurred_at"], "source": a["source"],
                "precedes": hw_action, "precedes_at": hw,
                "reason": "Timestamp is earlier than an action in a preceding stage.",
            })
        else:
            hw, hw_action = a["occurred_at"], a["action"]
    return warnings


@router.get("/stages")
def trail_stages(current_user: CurrentUser = Depends(get_current_user)):
    """The eight stages, for rendering the tracker skeleton."""
    return {"stages": workflow_stages.catalogue()}


@router.get("")
@router.get("/")
def list_tracked_permits(
    stage: Optional[str] = Query(None, description="RECORD..CLOSE"),
    q: Optional[str] = Query(None),
    limit: int = Query(200, le=500),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Every permit with its current stage and a summary of its trail."""
    where = ["p.organisation_id = :org"]
    params: Dict[str, object] = {"org": current_user.org_id, "lim": limit}
    if q:
        where.append("(p.work_description LIKE :q OR CAST(p.id AS CHAR) LIKE :q)")
        params["q"] = f"%{q.strip()}%"
    if stage:
        wanted = stage.strip().upper()
        statuses = [s for s, k in workflow_stages.PERMIT_STATUS_STAGE.items() if k == wanted]
        if not statuses:
            raise HTTPException(status_code=400, detail=f"Unknown stage '{stage}'")
        where.append("p.workflow_status IN :statuses")
        params["statuses"] = tuple(statuses)

    rows = db.execute(
        text(
            "SELECT p.*, ws.station_name, pt.permit_type_name "
            f"  FROM {TABLE} p "
            "  LEFT JOIN working_stations ws ON ws.id = p.location_station_id "
            "  LEFT JOIN permit_types pt ON pt.id = p.permit_type_id "
            f" WHERE {' AND '.join(where)} "
            " ORDER BY p.id DESC LIMIT :lim"
        ),
        params,
    ).mappings().all()

    # Counted over the whole table, not the page — the client renders these as
    # the stage filter's totals.
    stage_counts = {s.key: 0 for s in workflow_stages.STAGES}
    for r in db.execute(
        text(f"SELECT workflow_status, COUNT(*) AS n FROM {TABLE} "
             " WHERE organisation_id = :org GROUP BY workflow_status"),
        {"org": current_user.org_id},
    ).mappings().all():
        key = workflow_stages.stage_for(FAMILY, r["workflow_status"])
        if key:
            stage_counts[key] += r["n"]

    directory = _fetch_people(db, {r[c] for r in rows for c in _ACTOR_COLUMNS})
    now = datetime.now()
    items = []
    for r in rows:
        p = dict(r)
        actions = _build_actions(db, p)
        stage_key = workflow_stages.stage_for(FAMILY, p.get("workflow_status"))
        requester = directory.get(p.get("requested_by") or 0)
        approver = directory.get(p.get("approved_by") or 0)
        items.append({
            "id": p["id"], "reference": _ref(p["id"]), "family": FAMILY,
            "description": p.get("work_description"),
            "permit_type": p.get("permit_type_name"),
            "station_name": p.get("station_name"),
            "workflow_status": p.get("workflow_status"),
            "stage": stage_key,
            "stage_number": workflow_stages.stage_number(stage_key),
            "gate_status": p.get("gate_status"),
            "is_high_energy": bool(p.get("is_high_energy")),
            "validity_start": _iso(p.get("validity_start")),
            "validity_end": _iso(p.get("validity_end")),
            # A permit past its validity while still live is the live safety
            # problem — work may be continuing under a dead permit.
            "is_overdue": bool(
                p.get("validity_end") and p["validity_end"] < now
                and p.get("workflow_status") in workflow_stages.PERMIT_LIVE_STATUSES
            ),
            "requested_at": _iso(p.get("requested_at") or p.get("created_at")),
            "last_action_at": actions[-1]["occurred_at"] if actions else None,
            "action_count": len(actions),
            "requested_by_id": p.get("requested_by"),
            "requested_by_name": requester["name"] if requester else None,
            "approved_by_id": p.get("approved_by"),
            "approved_by_name": approver["name"] if approver else None,
            "auditor_verified": bool(p.get("auditor_verified_at")),
            "verification_result": p.get("verification_result"),
        })
    return {"count": len(items), "items": items, "stage_counts": stage_counts}


@router.get("/{permit_id}")
def permit_trail(
    permit_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """The full action-by-action trail for one permit, grouped by stage."""
    p = _row(db, permit_id, current_user.org_id)
    actions = _build_actions(db, p)
    current_stage = workflow_stages.stage_for(FAMILY, p.get("workflow_status"))
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
            state = "complete" if s.key == CLOSE else "current"
        else:
            # A stage the record has not reached yet can still hold a recorded
            # action, and calling that "Not reached" contradicts the entry shown
            # underneath it. Permits hit this routinely: the auditor verifies on
            # site while the permit is still `active` (stage 05), so VERIFY has
            # an action before the permit moves there. An action is evidence the
            # stage happened, so it reads complete.
            state = "complete" if entries else "pending"
        stages.append({
            "number": s.number, "key": s.key, "label": s.label,
            "description": s.description, "state": state,
            "entered_at": entries[0]["occurred_at"] if entries else None,
            "last_action_at": entries[-1]["occurred_at"] if entries else None,
            "action_count": len(entries), "actions": entries,
        })

    return {
        "record": {
            "id": p["id"], "reference": _ref(p["id"]), "family": FAMILY,
            "description": p.get("work_description"),
            "workflow_status": p.get("workflow_status"),
            "stage": current_stage, "stage_number": current_number or None,
            "gate_status": p.get("gate_status"),
            "gate_blocked_reason": p.get("gate_blocked_reason"),
            "is_high_energy": bool(p.get("is_high_energy")),
            "validity_start": _iso(p.get("validity_start")),
            "validity_end": _iso(p.get("validity_end")),
            "requested_at": _iso(p.get("requested_at") or p.get("created_at")),
            "suspension_reason": p.get("suspension_reason"),
            "rejection_reason": p.get("rejection_reason"),
            "verification_result": p.get("verification_result"),
            "verification_notes": p.get("verification_notes"),
        },
        "stages": stages,
        "actions": actions,
        "people": _build_people(db, p, actions),
        "named_in_report": {"witnesses": []},
        "unstaged_actions": [a for a in actions if not a["stage"]],
        "total_actions": len(actions),
        "total_stages": len(workflow_stages.STAGES),
        "skipped_stages": [s["key"] for s in stages if s["state"] == "skipped"],
        "chronology_warnings": _chronology_warnings(actions),
    }
