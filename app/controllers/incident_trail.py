"""Every action on an incident, from first capture to closure, for the admin.

The admin needs one place that answers "what has actually happened to this
incident, and who did it" without opening five screens. `/incident-workflow`
answers "what can I do next" for the role performing the work; this answers
"what was done, by whom, when" for the person accountable for the whole
lifecycle. Nothing here writes.

**Where the actions come from.** `audit_logs` is the table you would expect to
read and it is empty — nothing in the app writes to it (see audit_trail.py,
which hit the same wall). So the trail is reconstructed from the state the
workflow already records:

  * the ~15 workflow timestamp columns on `incidents`
  * `capa_actions` rows belonging to the incident
  * `domain_events` published against subject_family='incident'
  * `audit_logs`, still read, so the trail improves by itself the day
    something starts writing there

Every entry therefore corresponds to a transition that provably happened,
carries the actor who owns that column, and is tagged with one of the eight
stages from `workflow_stages`.

**One deliberate difference from `workflow_stages.stage_for`.** That function
maps a *status* to the stage whose work is still outstanding ("what is owed
next"). A trail entry is the opposite: a thing that already happened, so it is
tagged with the stage it belongs to. `approved_at` is the tail of INVESTIGATE
here, while the status `approved` maps to LEARN there. Both are right for their
own question; do not "fix" one to match the other.
"""
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.services import workflow_stages
from app.services.events import catalogue
from app.services.workflow_stages import (
    RECORD, ASSESS, RESPOND, INVESTIGATE, IMPROVE, VERIFY, LEARN, CLOSE,
)

router = APIRouter(prefix="/incident-trail", tags=["Incident Trail"])


# ── The timestamp columns, in lifecycle order ────────────────────────────────
#
# (timestamp column, stage, action label, actor column or None)
#
# `actor column` is the employees.id that owns the action. Where a column has no
# actor of its own the nearest owning role is used — acknowledgement and the
# investigation steps are the assigned supervisor's, which is what the workflow
# controller sets them from.
_TIMELINE: List[tuple] = [
    ("created_at",                  RECORD,      "Record created",                    "reported_by"),
    ("reported_at",                 RECORD,      "Incident reported",                 "reported_by"),
    ("severity_classified_at",      ASSESS,      "Severity classified",               None),
    ("statutory_authorised_at",     ASSESS,      "Statutory notification authorised",  "statutory_authorised_by"),
    ("acknowledged_at",             RESPOND,     "Acknowledged by supervisor",        "assigned_supervisor_id"),
    ("investigation_started_at",    INVESTIGATE, "Investigation started",             "assigned_supervisor_id"),
    ("escalated_at",                INVESTIGATE, "Escalated to manager",              "escalated_to_manager_id"),
    ("investigation_completed_at",  INVESTIGATE, "Investigation completed",           "assigned_supervisor_id"),
    ("approved_at",                 INVESTIGATE, "Investigation approved",            "escalated_to_manager_id"),
    ("capa_verified_at",            VERIFY,      "CAPA effectiveness verified",       "capa_verified_by"),
    ("auditor_verified_at",         VERIFY,      "Verified by auditor",               "auditor_verified_by"),
    ("closed_at",                   CLOSE,       "Incident closed",                   "escalated_to_manager_id"),
]

# Columns carrying detail worth showing next to the action that produced them.
_DETAIL_FOR: Dict[str, str] = {
    "severity_classified_at": "severity_trace",
    "investigation_completed_at": "root_cause",
    "escalated_at": "escalation_reason",
    "closed_at": "closure_notes",
    "capa_verified_at": "capa_verification_notes",
    "auditor_verified_at": "verification_notes",
    "statutory_authorised_at": "statutory_summary",
}

# Text/flag columns with no timestamp of their own. They are real actions, but
# the schema never recorded *when*, so they are anchored to the timestamp of the
# step that must have carried them and flagged `timestamp_inferred`. Anchoring
# beats dropping them (the LEARN stage would look empty on every incident) and
# beats inventing a time (which would read as fact).
_UNTIMED: List[tuple] = [
    # (column, stage, action label, anchor timestamp columns in preference order)
    ("immediate_actions_taken", RESPOND, "Immediate actions taken",
     ("acknowledged_at", "reported_at")),
    ("five_why_analysis", INVESTIGATE, "5-Why analysis recorded",
     ("investigation_completed_at", "investigation_started_at")),
    ("lessons_learned", LEARN, "Lesson recorded",
     ("closed_at", "approved_at", "investigation_completed_at")),
    ("communicated_to_teams", LEARN, "Lesson communicated to teams",
     ("closed_at", "approved_at")),
    ("manager_signature", CLOSE, "Manager sign-off", ("closed_at",)),
]

# The actor columns, and what each one means in the incident's process. The
# admin needs to see not only *who* touched the incident but in what capacity,
# and these columns are the only place that is recorded.
_ACTOR_COLUMNS: Dict[str, str] = {
    "reported_by": "Reporter",
    "assigned_supervisor_id": "Assigned supervisor",
    "escalated_to_manager_id": "Manager",
    "statutory_authorised_by": "Statutory authoriser",
    "capa_verified_by": "CAPA verifier",
    "auditor_verified_by": "Auditor",
}

_CAPA_OWNER_ROLE = "CAPA owner"

# domain_events event_type -> stage. Names come from services/events/catalogue
# verbatim (PascalCase, not dotted) — referencing the constants rather than
# retyping the strings keeps this from drifting when the catalogue changes.
# Only the closure events are actually emitted today; the rest are declared
# there and mapped here so they land in the right stage the day they start
# publishing. An unmapped type still appears with a null stage rather than
# being dropped — an event nobody mapped is worth seeing.
_EVENT_STAGE: Dict[str, str] = {
    catalogue.INCIDENT_REPORTED: RECORD,
    catalogue.INCIDENT_SEVERITY_CLASSIFIED: ASSESS,
    catalogue.CAPA_CLOSED: IMPROVE,
    catalogue.CAPA_OVERDUE: IMPROVE,
    catalogue.INCIDENT_CLOSED: CLOSE,
}


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def _fetch_people(db: Session, employee_ids: set) -> Dict[int, dict]:
    """employees.id -> the identifying record the admin needs. One query.

    `employees.id` *is* the employee id — there is no separate staff-code column
    anywhere in the schema (`users.employee_id` is a foreign key back to this
    same id, not a code). `EMP-<id>` is therefore a display convention, not a
    stored value, and is built here so every screen renders it identically.

    The login username is joined in where the employee has an account: the
    workflow columns store employee ids, but an admin chasing "who did this"
    generally needs the account, and only `users` bridges the two.
    """
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
            "employee_id": r["id"],
            "employee_ref": f"EMP-{r['id']}",
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


def _build_people(db: Session, inc: dict, actions: List[dict]) -> List[dict]:
    """Everyone who touched this incident, with what they did.

    Built from the actions rather than from the columns directly, so a person
    listed here always has the trail entries to back it up and the two can never
    disagree about who was involved.
    """
    # employee id -> the capacities they acted in, from the column that named them
    roles_by_person: Dict[int, set] = {}
    for column, role in _ACTOR_COLUMNS.items():
        emp_id = inc.get(column)
        if emp_id:
            roles_by_person.setdefault(int(emp_id), set()).add(role)

    acted: Dict[int, List[dict]] = {}
    for a in actions:
        if a.get("actor_id"):
            acted.setdefault(int(a["actor_id"]), []).append(a)
            if a["source"].startswith("capa_actions"):
                roles_by_person.setdefault(int(a["actor_id"]), set()).add(_CAPA_OWNER_ROLE)

    everyone = set(roles_by_person) | set(acted)
    directory = _fetch_people(db, everyone)

    people = []
    for emp_id in everyone:
        entries = acted.get(emp_id, [])
        times = [e["occurred_at"] for e in entries if e["occurred_at"]]
        person = directory.get(emp_id) or {
            # The id is on the incident but the employee row is gone. Say so
            # rather than dropping the person — a deleted actor is a finding.
            "employee_id": emp_id, "employee_ref": f"EMP-{emp_id}", "name": None,
            "job_role": None, "department": None, "employment_type": None,
            "is_active": False, "username": None, "email": None,
        }
        people.append({
            **person,
            "record_missing": emp_id not in directory,
            "workflow_roles": sorted(roles_by_person.get(emp_id, set())),
            "action_count": len(entries),
            "actions": [e["action"] for e in entries],
            "first_action_at": min(times) if times else None,
            "last_action_at": max(times) if times else None,
        })

    # Most involved first, then by name so the order is stable between calls.
    people.sort(key=lambda p: (-p["action_count"], p["name"] or "", p["employee_id"]))
    return people


def _named_in_report(inc: dict) -> dict:
    """People the report names who are not process actors.

    Kept separate from `people`, where every entry is backed by an employee row
    and a role in the process. A witness may be an employee — the form now picks
    them from the register and their id comes with the name — but they are not
    an actor in the workflow, and the injured party is free text either way.

    Witness labels are built by `report_trail_factory._witness_label`, the same
    helper the other families use, so a picked employee reads "Henry Jackson
    (EMP-21)" here exactly as it does on a near miss.
    """
    witnesses: List[str] = []
    raw = inc.get("witnesses_json")
    if raw:
        import json
        from app.controllers.report_trail_factory import _witness_label
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, list):
                witnesses = [_witness_label(w) for w in parsed]
            elif parsed:
                witnesses = [str(parsed)]
        except (ValueError, TypeError):
            witnesses = [str(raw)]

    return {
        "injured_person": inc.get("injured_person_name") or None,
        "injured_body_part": inc.get("injured_body_part") or None,
        "witnesses": [w for w in witnesses if w and w.strip()],
    }


def _incident_row(db: Session, incident_id: int, org_id: Optional[int]) -> dict:
    row = db.execute(
        text("SELECT * FROM incidents WHERE id = :id AND organisation_id = :org"),
        {"id": incident_id, "org": org_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    return dict(row)


def _build_actions(db: Session, inc: dict) -> List[dict]:
    """Every recorded action on one incident, oldest first."""
    actions: List[dict] = []

    # 1 ── the workflow timestamp columns
    for column, stage, label, actor_col in _TIMELINE:
        when = inc.get(column)
        if not when:
            continue
        detail_col = _DETAIL_FOR.get(column)
        detail = inc.get(detail_col) if detail_col else None
        actions.append({
            "stage": stage,
            "action": label,
            "detail": (str(detail)[:400] if detail else None),
            "actor_id": inc.get(actor_col) if actor_col else None,
            "occurred_at": when,
            "source": f"incidents.{column}",
            "timestamp_inferred": False,
            "reference": None,
        })

    # 2 ── the untimed columns, anchored to the step that carried them
    for column, stage, label, anchors in _UNTIMED:
        value = inc.get(column)
        if not value:
            continue
        anchor_at, anchor_col = None, None
        for candidate in anchors:
            if inc.get(candidate):
                anchor_at, anchor_col = inc[candidate], candidate
                break
        if not anchor_at:
            continue  # nothing to anchor to — the action cannot be placed in time
        detail = value if isinstance(value, str) else None
        actions.append({
            "stage": stage,
            "action": label,
            "detail": (detail[:400] if detail else None),
            "actor_id": None,
            "occurred_at": anchor_at,
            "source": f"incidents.{column}",
            "timestamp_inferred": True,
            "inferred_from": f"incidents.{anchor_col}",
            "reference": None,
        })

    # 3 ── CAPA actions: raised, and closed where the status says so
    capas = db.execute(
        text(
            "SELECT id, capa_ref, description, action_type, status, due_date, created_at, updated_at, "
            "       responsible_person_id, priority_band, effectiveness_rating "
            "  FROM capa_actions WHERE incident_id = :id ORDER BY created_at"
        ),
        {"id": inc["id"]},
    ).mappings().all()

    for capa in capas:
        # capa_ref is the same reference the CAPA list, its detail page and its
        # notifications show — building a fresh "CAPA-{id}" string here (no
        # padding, unlike the CAPA-{id:06d} stamped at creation) is how the
        # same action ends up under two different numbers on two screens.
        capa_reference = capa["capa_ref"] or f"CAPA-{capa['id']:06d}"
        actions.append({
            "stage": IMPROVE,
            "action": f"CAPA raised — {capa['action_type'] or 'action'}",
            "detail": (capa["description"] or "")[:400] or None,
            "actor_id": capa["responsible_person_id"],
            "occurred_at": capa["created_at"],
            "source": "capa_actions",
            "timestamp_inferred": False,
            "reference": capa_reference,
            "capa_status": capa["status"],
            "capa_due_date": _iso(capa["due_date"]),
            "capa_priority": capa["priority_band"],
        })
        # A closed CAPA has no closed_at column, only a status and updated_at.
        # updated_at is the best available evidence of when it changed.
        if (capa["status"] or "").strip().lower() in {"closed", "completed", "verified", "done"}:
            actions.append({
                "stage": IMPROVE,
                "action": f"CAPA completed — {capa['action_type'] or 'action'}",
                "detail": (capa["description"] or "")[:200] or None,
                "actor_id": capa["responsible_person_id"],
                "occurred_at": capa["updated_at"] or capa["created_at"],
                "source": "capa_actions.status",
                "timestamp_inferred": True,
                "inferred_from": "capa_actions.updated_at",
                "reference": capa_reference,
                "capa_status": capa["status"],
            })

    # 4 ── domain events published against this incident
    events = db.execute(
        text(
            "SELECT event_type, user_id, published_at, created_at, correlation_id "
            "  FROM domain_events "
            " WHERE subject_family = 'incident' AND subject_id = :id "
            " ORDER BY COALESCE(published_at, created_at)"
        ),
        {"id": inc["id"]},
    ).mappings().all()

    for ev in events:
        actions.append({
            "stage": _EVENT_STAGE.get(ev["event_type"]),
            "action": f"Event published — {ev['event_type']}",
            "detail": None,
            "actor_id": None,
            "occurred_at": ev["published_at"] or ev["created_at"],
            "source": "domain_events",
            "timestamp_inferred": False,
            "reference": ev["correlation_id"],
        })

    # 5 ── audit_logs. Empty today; read anyway so the trail deepens on its own
    #      the day anything starts writing there.
    logs = db.execute(
        text(
            "SELECT action, module, previous_value, new_value, employee_id, created_at "
            "  FROM audit_logs "
            " WHERE record_id = :id AND LOWER(module) IN ('incident', 'incidents') "
            " ORDER BY created_at"
        ),
        {"id": inc["id"]},
    ).mappings().all()

    for log in logs:
        actions.append({
            "stage": None,
            "action": log["action"] or "Change logged",
            "detail": (
                f"{log['previous_value']} → {log['new_value']}"
                if log["new_value"] else None
            ),
            "actor_id": log["employee_id"],
            "occurred_at": log["created_at"],
            "source": "audit_logs",
            "timestamp_inferred": False,
            "reference": None,
        })

    # Ordered by stage first, timestamp second — NOT by timestamp alone.
    #
    # The timestamps on an incident are written from three different clocks:
    # `created_at`/`updated_at` use MySQL `func.now()` (server local time),
    # most workflow columns use `datetime.utcnow()`, and `auditor_verified_at`
    # uses `datetime.now()` (Python local). On an IST server that is a 5h30m
    # spread, so 10 of 14 acknowledged incidents in this database carry an
    # `acknowledged_at` *earlier* than their `reported_at`. Sorting purely on
    # time makes the lifecycle read backwards — closure before capture — which
    # looks like a workflow bug rather than the clock bug it is.
    #
    # Stage order is the thing the admin actually asked to see, and it is
    # derived from the schema rather than the clock, so it is trustworthy.
    # The bad timestamps are reported separately as `chronology_warnings`
    # rather than hidden: see `_chronology_warnings`.
    actions.sort(key=lambda a: (
        workflow_stages.stage_number(a["stage"]) or 99,
        a["occurred_at"] is None,
        a["occurred_at"],
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


def _chronology_warnings(actions: List[dict]) -> List[dict]:
    """Actions whose timestamp contradicts their position in the lifecycle.

    A later stage carrying an earlier timestamp than a stage before it means one
    of the two was written from a different clock. Surfaced so the admin sees
    the data problem instead of a timeline that silently reads out of order.
    """
    warnings: List[dict] = []
    high_water = None
    high_water_action = None
    for a in actions:
        if not a["occurred_at"] or a["stage_number"] is None:
            continue
        if high_water and a["occurred_at"] < high_water:
            warnings.append({
                "action": a["action"],
                "stage": a["stage"],
                "occurred_at": a["occurred_at"],
                "source": a["source"],
                "precedes": high_water_action,
                "precedes_at": high_water,
                "reason": "Timestamp is earlier than an action in a preceding stage.",
            })
        else:
            high_water, high_water_action = a["occurred_at"], a["action"]
    return warnings


@router.get("/stages")
def trail_stages(current_user: CurrentUser = Depends(get_current_user)):
    """The eight stages, for rendering the tracker skeleton."""
    return {"stages": workflow_stages.catalogue()}


@router.get("")
@router.get("/")
def list_tracked_incidents(
    stage: Optional[str] = Query(None, description="RECORD..CLOSE"),
    status: Optional[str] = Query(None, description="workflow_status"),
    q: Optional[str] = Query(None, description="Free text over description / id"),
    limit: int = Query(200, le=500),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Every incident with its current stage and how far it has been tracked.

    One row per incident, carrying the counts the admin table needs, so the
    tracker list does not have to fetch a full trail per row.
    """
    rows = db.execute(
        text(
            "SELECT id, description, incident_type, severity, severity_label, severity_priority, "
            "       workflow_status, reported_at, created_at, closed_at, investigation_due_at, "
            "       is_hipo, is_recurring_pattern, statutory_reportable, "
            f"      {', '.join(_ACTOR_COLUMNS)} "
            "  FROM incidents WHERE organisation_id = :org "
            " ORDER BY COALESCE(reported_at, created_at) DESC LIMIT :lim"
        ),
        {"org": current_user.org_id, "lim": limit},
    ).mappings().all()

    if not rows:
        return {"count": 0, "items": [], "stage_counts": {}}

    ids = [r["id"] for r in rows]

    # CAPA counts for every incident in one query rather than one per row.
    capa_rows = db.execute(
        text(
            "SELECT incident_id, COUNT(*) AS total, "
            "       SUM(CASE WHEN LOWER(status) IN ('closed','completed','verified','done') "
            "                THEN 1 ELSE 0 END) AS closed "
            "  FROM capa_actions WHERE incident_id IN :ids GROUP BY incident_id"
        ),
        {"ids": tuple(ids)},
    ).mappings().all()
    capa_by_incident = {r["incident_id"]: r for r in capa_rows}

    # Count recorded timestamps per incident without pulling every column back:
    # the same set the trail builds from, so the number the list shows agrees
    # with the number of entries the detail view renders.
    ts_columns = [c for c, _, _, _ in _TIMELINE]
    ts_rows = db.execute(
        text(
            f"SELECT id, {', '.join(ts_columns)} FROM incidents WHERE id IN :ids"
        ),
        {"ids": tuple(ids)},
    ).mappings().all()
    ts_by_incident = {r["id"]: r for r in ts_rows}

    # Every actor named on any listed incident, plus the CAPA owners, resolved
    # in one query so each row can show who is involved without a lookup per row.
    capa_owners = db.execute(
        text(
            "SELECT DISTINCT incident_id, responsible_person_id FROM capa_actions "
            " WHERE incident_id IN :ids AND responsible_person_id IS NOT NULL"
        ),
        {"ids": tuple(ids)},
    ).mappings().all()
    owners_by_incident: Dict[int, set] = {}
    for o in capa_owners:
        owners_by_incident.setdefault(o["incident_id"], set()).add(o["responsible_person_id"])

    directory = _fetch_people(
        db,
        {r[col] for r in rows for col in _ACTOR_COLUMNS}
        | {emp for owners in owners_by_incident.values() for emp in owners},
    )

    from datetime import datetime
    now = datetime.utcnow()

    items = []
    stage_counts: Dict[str, int] = {s.key: 0 for s in workflow_stages.STAGES}

    for r in rows:
        stage_key = workflow_stages.stage_for("incident", r["workflow_status"])
        if stage_key:
            stage_counts[stage_key] += 1
        if stage and (stage_key or "") != stage.strip().upper():
            continue
        if status and (r["workflow_status"] or "") != status:
            continue
        if q:
            needle = q.strip().lower()
            haystack = f"{r['id']} {r['description'] or ''} {r['incident_type'] or ''}".lower()
            if needle not in haystack:
                continue

        ts = ts_by_incident.get(r["id"], {})
        recorded = [ts.get(c) for c in ts_columns if ts.get(c)]
        capa = capa_by_incident.get(r["id"])
        due = r["investigation_due_at"]

        # Who is involved, in the capacity the naming column gives them. Ordered
        # by the lifecycle (reporter first) rather than by id, so the list reads
        # the same way the trail does.
        participants = []
        seen: set = set()
        for col, role in _ACTOR_COLUMNS.items():
            emp_id = r[col]
            if not emp_id or emp_id in seen:
                continue
            seen.add(emp_id)
            person = directory.get(emp_id)
            participants.append({
                "employee_id": emp_id,
                "employee_ref": f"EMP-{emp_id}",
                "name": person["name"] if person else None,
                "job_role": person["job_role"] if person else None,
                "workflow_role": role,
            })
        for emp_id in sorted(owners_by_incident.get(r["id"], set())):
            if emp_id in seen:
                continue
            seen.add(emp_id)
            person = directory.get(emp_id)
            participants.append({
                "employee_id": emp_id,
                "employee_ref": f"EMP-{emp_id}",
                "name": person["name"] if person else None,
                "job_role": person["job_role"] if person else None,
                "workflow_role": _CAPA_OWNER_ROLE,
            })

        items.append({
            "id": r["id"],
            "reference": f"INC-{r['id']}",
            "description": (r["description"] or "")[:160],
            "incident_type": r["incident_type"],
            "severity": r["severity"],
            "severity_label": r["severity_label"],
            "priority": r["severity_priority"],
            "workflow_status": r["workflow_status"],
            "stage": stage_key,
            "stage_number": workflow_stages.stage_number(stage_key),
            "reported_at": _iso(r["reported_at"] or r["created_at"]),
            "closed_at": _iso(r["closed_at"]),
            "last_action_at": _iso(max(recorded)) if recorded else None,
            "action_count": len(recorded) + (capa["total"] if capa else 0),
            "capa_total": int(capa["total"]) if capa else 0,
            "capa_closed": int(capa["closed"] or 0) if capa else 0,
            "is_hipo": bool(r["is_hipo"]),
            "is_recurring": bool(r["is_recurring_pattern"]),
            "statutory_reportable": bool(r["statutory_reportable"]),
            "is_overdue": bool(due and not r["closed_at"] and due < now),
            "reported_by_id": r["reported_by"],
            "reported_by_name": (directory.get(r["reported_by"]) or {}).get("name"),
            "supervisor_id": r["assigned_supervisor_id"],
            "supervisor_name": (directory.get(r["assigned_supervisor_id"]) or {}).get("name"),
            "manager_id": r["escalated_to_manager_id"],
            "manager_name": (directory.get(r["escalated_to_manager_id"]) or {}).get("name"),
            "participants": participants,
            "participant_count": len(participants),
        })

    return {"count": len(items), "items": items, "stage_counts": stage_counts}


@router.get("/{incident_id}")
def incident_trail(
    incident_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """The full action-by-action trail for one incident, grouped by stage.

    `stages` carries all eight whether or not anything happened in them — a
    stage that was skipped is exactly what the admin is looking for, so it has
    to be visible rather than absent.
    """
    inc = _incident_row(db, incident_id, current_user.org_id)
    actions = _build_actions(db, inc)

    current_stage = workflow_stages.stage_for("incident", inc.get("workflow_status"))
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
            # Reaching CLOSE *is* the completion — there is no ninth stage to
            # move on to, so the last stage must not read "in progress" on an
            # incident that is finished.
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

    unstaged = [a for a in actions if not a["stage"]]

    return {
        "incident": {
            "id": inc["id"],
            "reference": f"INC-{inc['id']}",
            "description": inc.get("description"),
            "incident_type": inc.get("incident_type"),
            "severity": inc.get("severity"),
            "severity_label": inc.get("severity_label"),
            "priority": inc.get("severity_priority"),
            "workflow_status": inc.get("workflow_status"),
            "stage": current_stage,
            "stage_number": current_number or None,
            "is_hipo": bool(inc.get("is_hipo")),
            "is_recurring": bool(inc.get("is_recurring_pattern")),
            "statutory_reportable": bool(inc.get("statutory_reportable")),
            "incident_date_time": _iso(inc.get("incident_date_time")),
            "reported_at": _iso(inc.get("reported_at") or inc.get("created_at")),
            "closed_at": _iso(inc.get("closed_at")),
            "root_cause": inc.get("root_cause"),
            "closure_notes": inc.get("closure_notes"),
            "lessons_learned": inc.get("lessons_learned"),
        },
        "stages": stages,
        "actions": actions,
        "people": _build_people(db, inc, actions),
        "named_in_report": _named_in_report(inc),
        "unstaged_actions": unstaged,
        "total_actions": len(actions),
        "total_stages": len(workflow_stages.STAGES),
        "skipped_stages": [s["key"] for s in stages if s["state"] == "skipped"],
        "chronology_warnings": _chronology_warnings(actions),
    }
