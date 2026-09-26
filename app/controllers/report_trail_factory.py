"""Builds an admin lifecycle-tracking router per report family.

The report families' twin of `/incident-trail`, and deliberately the same
response shape: the web console renders one lifecycle component, and a second
shape would mean a second renderer that drifts from the first.

Why a factory rather than a module per family: near misses, unsafe acts and risk
reports all carry `ReportWorkflowMixin`, so the timestamp columns the trail is
reconstructed from are *identical* across the three. Three copies would disagree
the first time a column was added — the same reasoning that put their workflow
routers behind `report_workflow_factory`.

**Where the actions come from.** `audit_logs` is the table you would expect to
read and nothing writes to it (see audit_trail.py, which hit the same wall). So
the trail is reconstructed from the state the workflow already records: the
workflow timestamp columns, and the `capa_actions` rows linked by the
polymorphic (subject_family, subject_id) pair from migration 056.

A column with a timestamp of its own is reported as fact. A column without one
(a root cause, a lesson) is anchored to the step that must have carried it and
flagged `timestamp_inferred`, so the admin can tell what was recorded from what
was deduced.

**One deliberate difference from `workflow_stages.stage_for`.** That maps a
*status* to the stage whose work is still outstanding ("what is owed next"). A
trail entry is the opposite — a thing that already happened — so it is tagged
with the stage it belongs to. `approved_at` is the tail of INVESTIGATE here,
while the status `approved` maps to LEARN there. Both are right for their own
question; do not "fix" one to match the other.
"""
import json
from datetime import datetime
from typing import Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import CurrentUser, get_current_user
from app.services import workflow_stages
from app.services.workflow_stages import (
    ASSESS, CLOSE, IMPROVE, INVESTIGATE, LEARN, RECORD, RESPOND, VERIFY,
)

# ── Timestamped actions: (column, stage, label, actor column) ────────────────
#
# In lifecycle order. Each row is something the record can prove happened,
# because a moment was recorded against it. Where a column has no actor of its
# own the nearest owning role is used — acknowledgement and the investigation
# steps are the assigned supervisor's, which is what the workflow controller
# sets them from.
_TIMELINE: List[tuple] = [
    ("created_at",                 RECORD,      "Record created",               "reported_by"),
    ("reported_at",                RECORD,      "Reported by worker",           "reported_by"),
    ("assessed_at",                ASSESS,      "Triaged",                      None),
    ("acknowledged_at",            RESPOND,     "Acknowledged by supervisor",   "assigned_supervisor_id"),
    ("investigation_started_at",   INVESTIGATE, "Investigation started",        "assigned_supervisor_id"),
    ("escalated_at",               INVESTIGATE, "Escalated to manager",         "escalated_to_manager_id"),
    ("investigation_completed_at", INVESTIGATE, "Investigation completed",      "assigned_supervisor_id"),
    ("approved_at",                INVESTIGATE, "Investigation approved",       "escalated_to_manager_id"),
    ("capa_verified_at",           VERIFY,      "CAPA effectiveness verified",  "capa_verified_by"),
    # Post-closure assurance. It gates nothing — the auditor observes the chain,
    # they do not drive it — but it is still an action worth showing.
    ("auditor_verified_at",        VERIFY,      "Verified by auditor",          "auditor_verified_by"),
    ("closed_at",                  CLOSE,       "Closed by manager",            "escalated_to_manager_id"),
]

_DETAIL_FOR: Dict[str, str] = {
    "assessed_at": "assessment_trace",
    "escalated_at": "escalation_reason",
    "investigation_completed_at": "root_cause",
    "capa_verified_at": "capa_verification_notes",
    "auditor_verified_at": "verification_notes",
    "closed_at": "closure_notes",
}

# Text columns with no timestamp of their own. Real actions the schema never
# timed, anchored to the step that must have carried them. Anchoring beats
# dropping them (LEARN would look empty on every record) and beats inventing a
# time, which would read as fact.
_UNTIMED: List[tuple] = [
    ("immediate_actions_taken", RESPOND, "Immediate actions taken",
     ("acknowledged_at", "reported_at")),
    ("five_why_analysis", INVESTIGATE, "5-Why analysis recorded",
     ("investigation_completed_at", "investigation_started_at")),
    ("supervisor_signature", INVESTIGATE, "Supervisor sign-off",
     ("investigation_completed_at",)),
    ("lessons_learned", LEARN, "Lesson recorded",
     ("closed_at", "approved_at", "investigation_completed_at")),
    ("manager_signature", CLOSE, "Manager sign-off", ("closed_at",)),
]

_ACTOR_COLUMNS: Dict[str, str] = {
    "reported_by": "Reporter",
    "assigned_supervisor_id": "Assigned supervisor",
    "escalated_to_manager_id": "Manager",
    "capa_verified_by": "CAPA verifier",
    "auditor_verified_by": "Auditor",
}

_CAPA_OWNER_ROLE = "CAPA owner"
_CAPA_CLOSED = ("closed", "completed", "verified", "done")


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def _fetch_people(db: Session, employee_ids: set) -> Dict[int, dict]:
    """employees.id -> the identifying record the admin needs. One query.

    `EMP-<id>` is a display convention, not a stored value — there is no staff
    code column in the schema — and is built here so every screen renders it
    identically. The login username is joined in because an admin chasing "who
    did this" generally needs the account, and only `users` bridges the two.
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


def _witness_label(w) -> str:
    """One witness, as the admin reads them.

    A witness chosen from the employee register arrives as a dict and is shown
    with the staff code the rest of the console prints — "Henry Jackson
    (EMP-21)". One typed by hand is a bare string and stays one: there is no id
    to show, because a contractor or a visitor does not have one.
    """
    if not isinstance(w, dict):
        return str(w)
    name = w.get("name") or w.get("full_name") or ""
    emp_id = w.get("employee_id")
    if name and emp_id:
        return f"{name} (EMP-{emp_id})"
    return str(name or w)


def _witnesses(row: dict) -> List[str]:
    """Witnesses on the report, employee-linked where the reporter picked one."""
    raw = row.get("witnesses_json")
    if not raw:
        return []
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return [str(raw)]
    if isinstance(parsed, list):
        names = [_witness_label(w) for w in parsed]
    elif parsed:
        names = [str(parsed)]
    else:
        names = []
    return [n for n in names if n and n.strip()]


def build_trail_router(
    *,
    report_type: str,
    table: str,
    prefix: str,
    tag: str,
    noun: str,
    ref_prefix: str,
    extra_list_fields: Optional[Callable[[dict], dict]] = None,
    extra_record_fields: Optional[Callable[[dict], dict]] = None,
) -> APIRouter:
    """Return an admin trail router for one report family.

    `ref_prefix` is the human reference stem (NEA / UNS / RIS) and matches what
    the mobile queue and the closure event already print, so one record is named
    identically wherever the admin meets it.

    `extra_list_fields` / `extra_record_fields` take the raw row and return the
    columns that only one family has. What the factory emits itself is exactly
    what `ReportWorkflowMixin` guarantees, so it cannot drift into a union of
    every table it serves — before the hooks existed the near miss trio
    (potential_consequence / underlying_cause / event_date_time) sat in the
    shared block and rode along on every other family as three permanent nulls.
    They now come from `near_miss_trail`, which is the only router that has
    those columns, and the response it returns is unchanged.
    """
    router = APIRouter(prefix=prefix, tags=[tag])

    def _row(db: Session, record_id: int, org_id: Optional[int]) -> dict:
        row = db.execute(
            text(f"SELECT * FROM {table} WHERE id = :id AND organisation_id = :org"),
            {"id": record_id, "org": org_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail=f"{noun.capitalize()} {record_id} not found")
        return dict(row)

    def _capas(db: Session, record_ids: List[int]) -> Dict[int, List[dict]]:
        """Corrective actions for a set of records, by the polymorphic pair."""
        if not record_ids:
            return {}
        rows = db.execute(
            text(
                "SELECT id, subject_id, capa_ref, description, action_type, status, due_date, "
                "       created_at, updated_at, responsible_person_id, priority_band, "
                "       effectiveness_rating "
                "  FROM capa_actions "
                " WHERE subject_family = :fam AND subject_id IN :ids "
                " ORDER BY created_at"
            ),
            {"fam": report_type, "ids": tuple(record_ids)},
        ).mappings().all()
        out: Dict[int, List[dict]] = {}
        for r in rows:
            out.setdefault(r["subject_id"], []).append(dict(r))
        return out

    def _build_actions(db: Session, row: dict, capas: List[dict]) -> List[dict]:
        """Every recorded action on one record, in lifecycle order."""
        actions: List[dict] = []

        # 1 ── the workflow timestamp columns
        for column, stage, label, actor_col in _TIMELINE:
            when = row.get(column)
            if not when:
                continue
            detail_col = _DETAIL_FOR.get(column)
            detail = row.get(detail_col) if detail_col else None
            actions.append({
                "stage": stage,
                "action": label,
                "detail": (str(detail)[:400] if detail else None),
                "actor_id": row.get(actor_col) if actor_col else None,
                "occurred_at": when,
                "source": f"{table}.{column}",
                "timestamp_inferred": False,
                "reference": None,
            })

        # 2 ── the untimed columns, anchored to the step that carried them
        for column, stage, label, anchors in _UNTIMED:
            value = row.get(column)
            if not value:
                continue
            anchor_at, anchor_col = None, None
            for candidate in anchors:
                if row.get(candidate):
                    anchor_at, anchor_col = row[candidate], candidate
                    break
            if not anchor_at:
                continue  # nothing to anchor to — it cannot be placed in time
            actions.append({
                "stage": stage,
                "action": label,
                "detail": (value[:400] if isinstance(value, str) else None),
                "actor_id": None,
                "occurred_at": anchor_at,
                "source": f"{table}.{column}",
                "timestamp_inferred": True,
                "inferred_from": f"{table}.{anchor_col}",
                "reference": None,
            })

        # 3 ── corrective actions: raised, and closed where the status says so
        for c in capas:
            ref = c.get("capa_ref") or f"CAPA-{c['id']:06d}"
            if c.get("created_at"):
                actions.append({
                    "stage": IMPROVE,
                    "action": f"Corrective action raised ({c.get('action_type') or 'Corrective'})",
                    "detail": (c.get("description") or "")[:400] or None,
                    "actor_id": c.get("responsible_person_id"),
                    "occurred_at": c["created_at"],
                    "source": f"capa_actions.{c['id']}.created_at",
                    "timestamp_inferred": False,
                    "reference": ref,
                    "capa_status": c.get("status"),
                })
            if (c.get("status") or "").strip().lower() in _CAPA_CLOSED and c.get("updated_at"):
                rating = c.get("effectiveness_rating")
                actions.append({
                    "stage": IMPROVE,
                    "action": "Corrective action signed off",
                    "detail": (f"Effectiveness rated {rating}/5" if rating else None),
                    "actor_id": c.get("responsible_person_id"),
                    "occurred_at": c["updated_at"],
                    "source": f"capa_actions.{c['id']}.updated_at",
                    # `updated_at` moves on any write, so it is the best evidence
                    # of when it closed but not proof of it.
                    "timestamp_inferred": True,
                    "inferred_from": f"capa_actions.{c['id']}.updated_at",
                    "reference": ref,
                    "capa_status": c.get("status"),
                })

        # Sorted by stage first, then time — deliberately not by time alone.
        #
        # The columns are written from three different clocks: `created_at`
        # uses the MySQL server's local time, the workflow columns use
        # `datetime.now()` from Python, and older rows carry `utcnow()`. On an
        # IST server that is a 5h30m spread, which is enough to put an
        # acknowledgement *before* the report that triggered it and make the
        # lifecycle read backwards — a clock bug that looks like a workflow bug.
        # Stage order comes from the schema rather than the clock, so it is the
        # trustworthy axis. Contradictory timestamps are surfaced rather than
        # hidden — see `chronology_warnings` on the detail response.
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

    def _build_people(db: Session, row: dict, actions: List[dict]) -> List[dict]:
        """Everyone who touched this record, with what they did.

        Built from the actions rather than the columns directly, so a person
        listed here always has trail entries to back it up.
        """
        roles_by_person: Dict[int, set] = {}
        for column, role in _ACTOR_COLUMNS.items():
            emp_id = row.get(column)
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
                # The id is on the record but the employee row is gone. Say so
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

        people.sort(key=lambda p: (-p["action_count"], p["name"] or "", p["employee_id"]))
        return people

    def _chronology_warnings(actions: List[dict]) -> List[dict]:
        """Actions whose timestamp contradicts their position in the lifecycle.

        A later stage carrying an earlier timestamp than a stage before it means
        one of the two was written from a different clock. Surfaced so the admin
        sees the data problem instead of a timeline that silently reads wrong.
        """
        warnings: List[dict] = []
        high_water: Optional[str] = None
        high_water_action: Optional[str] = None
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

    # ══════════════════════════════════════════════════════════════════════════
    @router.get("/stages")
    def trail_stages(current_user: CurrentUser = Depends(get_current_user)):
        """The eight stages, for rendering the tracker skeleton."""
        return {"stages": workflow_stages.catalogue()}

    @router.get("")
    @router.get("/")
    def list_tracked(
        stage: Optional[str] = Query(None, description="RECORD..CLOSE"),
        q: Optional[str] = Query(None, description="Free text over description / reference"),
        limit: int = Query(200, le=500),
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        """Every record with its current stage and how far it has been tracked.

        One row per record, carrying the counts the admin table needs, so the
        list does not have to fetch a full trail per row.
        """
        where = [f"n.organisation_id = :org"]
        params: Dict[str, object] = {"org": current_user.org_id, "lim": limit}
        if q:
            where.append("(n.description LIKE :q OR CAST(n.id AS CHAR) LIKE :q)")
            params["q"] = f"%{q.strip()}%"

        # Filtering by stage means filtering by every status that maps to it,
        # done in SQL because LIMIT applies first — a post-filter on a rare
        # stage would return a nearly empty page while the table held plenty.
        if stage:
            wanted = stage.strip().upper()
            statuses = [
                s for s, key in workflow_stages.REPORT_STATUS_STAGE.items() if key == wanted
            ]
            if not statuses:
                raise HTTPException(status_code=400, detail=f"Unknown stage '{stage}'")
            where.append("n.workflow_status IN :statuses")
            params["statuses"] = tuple(statuses)

        rows = db.execute(
            text(
                "SELECT n.*, ws.station_name "
                f"  FROM {table} n "
                "  LEFT JOIN working_stations ws ON ws.id = n.location_station_id "
                f" WHERE {' AND '.join(where)} "
                " ORDER BY COALESCE(n.reported_at, n.created_at) DESC LIMIT :lim"
            ),
            params,
        ).mappings().all()

        # Counted over the whole table, not over `rows` — those are LIMITed and
        # the client renders these as the stage filter's totals. Counting the
        # page would make the pills shrink as the user narrowed the list.
        stage_counts = {s.key: 0 for s in workflow_stages.STAGES}
        for r in db.execute(
            text(
                f"SELECT workflow_status, COUNT(*) AS n FROM {table} "
                " WHERE organisation_id = :org GROUP BY workflow_status"
            ),
            {"org": current_user.org_id},
        ).mappings().all():
            key = workflow_stages.stage_for(report_type, r["workflow_status"])
            if key:
                stage_counts[key] += r["n"]

        record_ids = [r["id"] for r in rows]
        capa_by_record = _capas(db, record_ids)
        directory = _fetch_people(
            db,
            {r[col] for r in rows for col in _ACTOR_COLUMNS}
            | {c["responsible_person_id"] for cs in capa_by_record.values() for c in cs},
        )
        now = datetime.now()

        items = []
        for r in rows:
            row = dict(r)
            capas = capa_by_record.get(row["id"], [])
            actions = _build_actions(db, row, capas)
            stage_key = workflow_stages.stage_for(report_type, row.get("workflow_status"))
            open_capas = [
                c for c in capas
                if (c.get("status") or "").strip().lower() not in _CAPA_CLOSED
            ]
            due = row.get("response_due_at")
            reporter = directory.get(row.get("reported_by") or 0)
            supervisor = directory.get(row.get("assigned_supervisor_id") or 0)
            items.append({
                "id": row["id"],
                "reference": f"{ref_prefix}-{row['id']}",
                "family": report_type,
                "description": row.get("description"),
                "station_name": row.get("station_name"),
                "severity": row.get("severity"),
                "priority": row.get("assessed_priority"),
                "severity_label": row.get("assessed_label"),
                "workflow_status": row.get("workflow_status"),
                "stage": stage_key,
                "stage_number": workflow_stages.stage_number(stage_key),
                "is_hipo": bool(row.get("is_hipo")),
                "is_recurring": bool(row.get("is_recurring_pattern")),
                "reported_at": _iso(row.get("reported_at") or row.get("created_at")),
                "closed_at": _iso(row.get("closed_at")),
                "response_due_at": _iso(due),
                "is_overdue": bool(
                    due and row.get("workflow_status") != "closed" and due < now
                ),
                "last_action_at": actions[-1]["occurred_at"] if actions else None,
                "action_count": len(actions),
                "capa_total": len(capas),
                "capa_open": len(open_capas),
                "reported_by_id": row.get("reported_by"),
                "reported_by_name": reporter["name"] if reporter else None,
                "supervisor_id": row.get("assigned_supervisor_id"),
                "supervisor_name": supervisor["name"] if supervisor else None,
                "auditor_verified": bool(row.get("auditor_verified_at")),
                **(extra_list_fields(row) if extra_list_fields else {}),
            })

        # The stage filter is applied in SQL above; `items` is already narrowed.
        return {"count": len(items), "items": items, "stage_counts": stage_counts}

    @router.get("/{record_id}")
    def record_trail(
        record_id: int,
        db: Session = Depends(get_db),
        current_user: CurrentUser = Depends(get_current_user),
    ):
        """The full action-by-action trail for one record, grouped by stage.

        `stages` carries all eight whether or not anything happened in them — a
        stage that was skipped is exactly what the admin is looking for, so it
        has to be visible rather than absent.
        """
        row = _row(db, record_id, current_user.org_id)
        capas = _capas(db, [record_id]).get(record_id, [])
        actions = _build_actions(db, row, capas)

        current_stage = workflow_stages.stage_for(report_type, row.get("workflow_status"))
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
                # Reaching CLOSE *is* the completion — there is no ninth stage,
                # so the last stage must not read "in progress" once finished.
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
            "record": {
                "id": row["id"],
                "reference": f"{ref_prefix}-{row['id']}",
                "family": report_type,
                "description": row.get("description"),
                "severity": row.get("severity"),
                "severity_label": row.get("assessed_label"),
                "priority": row.get("assessed_priority"),
                "workflow_status": row.get("workflow_status"),
                "stage": current_stage,
                "stage_number": current_number or None,
                "is_hipo": bool(row.get("is_hipo")),
                "is_recurring": bool(row.get("is_recurring_pattern")),
                "reported_at": _iso(row.get("reported_at") or row.get("created_at")),
                "closed_at": _iso(row.get("closed_at")),
                "root_cause": row.get("root_cause"),
                "closure_notes": row.get("closure_notes"),
                "lessons_learned": row.get("lessons_learned"),
                "verification_result": row.get("verification_result"),
                **(extra_record_fields(row) if extra_record_fields else {}),
            },
            "stages": stages,
            "actions": actions,
            "people": _build_people(db, row, actions),
            "named_in_report": {"witnesses": _witnesses(row)},
            "unstaged_actions": [a for a in actions if not a["stage"]],
            "total_actions": len(actions),
            "total_stages": len(workflow_stages.STAGES),
            "skipped_stages": [s["key"] for s in stages if s["state"] == "skipped"],
            "chronology_warnings": _chronology_warnings(actions),
        }

    return router
