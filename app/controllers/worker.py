import json
from datetime import datetime, date, time, timedelta
from typing import Any, List, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import get_current_user, require_valid_org, CurrentUser
from app.services import workflow_stages
from app.services import supervisor_routing
from app.utils import report_media

router = APIRouter(prefix="/worker", tags=["Worker Mobile App"])


# All routes here are consumed by the mobile Worker app under the "/worker" prefix.
# (Auth refresh at '/auth/employee/refresh' lives in the auth router, not here.)


def _employee_id(db: Session, user: CurrentUser):
    """Employee row id linked to the logged-in user, or None if unlinked.

    Used to scope dashboard data to the signed-in worker instead of the whole org.
    """
    return db.execute(
        text("SELECT employee_id FROM users WHERE id = :uid"),
        {"uid": user.user_id},
    ).scalar()


# ─── Tasks Endpoints ──────────────────────────────────────────────────────────

@router.get("/tasks")
def list_tasks(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    """Fetch tasks (CAPA actions) assigned to the logged-in employee."""
    # Find employee linked to this user
    user_row = db.execute(
        text("SELECT employee_id FROM users WHERE id = :uid"),
        {"uid": current_user.user_id}
    ).mappings().first()

    emp_id = user_row["employee_id"] if user_row else None
    
    # Query CAPA actions
    query_str = "SELECT * FROM capa_actions WHERE organisation_id = :org_id"
    params = {"org_id": current_user.org_id}
    
    if emp_id:
        query_str += " AND responsible_person_id = :emp_id"
        params["emp_id"] = emp_id

    if status:
        query_str += " AND status = :status"
        params["status"] = status

    rows = db.execute(text(query_str), params).mappings().all()

    # Map database capa_actions to the frontend Task interface
    items = []
    for r in rows:
        items.append({
          "id": str(r["id"]),
          "title": r["action_type"] or "Safety Compliance Action",
          "location": r["root_cause_addressed"] or "Zone B - Sector 4",
          "priority": r["status"] == "Overdue" and "high" or "medium",
          "type": "checklist",
          "status": r["status"].lower() == "completed" and "completed" or "pending",
          "due_at": r["due_date"].isoformat() if r["due_date"] else None,
          "steps": [
              { "id": "1", "title": r["description"] or "Inspect area and check compliance", "completed": r["status"].lower() == "completed" }
          ]
        })

    # No mock fallback: an empty list is the truthful per-worker result when this
    # employee has no CAPA tasks assigned. The app renders its own empty state.
    return {"success": True, "data": {"items": items, "total": len(items)}}


# NOTE: This static route MUST be declared before "/tasks/{id}", otherwise
# FastAPI matches "shift-summary" as an {id} and this handler never runs.
@router.get("/tasks/shift-summary")
def get_shift_summary(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    emp_id = _employee_id(db, current_user)
    params = {"org_id": current_user.org_id}

    # Scope CAPA tasks to the ones this worker is responsible for.
    task_where = "organisation_id = :org_id"
    if emp_id:
        task_where += " AND responsible_person_id = :emp_id"
        params["emp_id"] = emp_id

    total_capas = db.execute(
        text(f"SELECT COUNT(*) FROM capa_actions WHERE {task_where}"), params
    ).scalar() or 0

    completed_capas = db.execute(
        text(f"SELECT COUNT(*) FROM capa_actions WHERE {task_where} AND status = 'Completed'"), params
    ).scalar() or 0

    # Scope active permits to ones this worker raised or acknowledged.
    permit_where = "organisation_id = :org_id AND status = 'Active'"
    if emp_id:
        permit_where += " AND (requested_by = :emp_id OR acknowledged_by = :emp_id)"

    active_permits = db.execute(
        text(f"SELECT COUNT(*) FROM permits_to_work WHERE {permit_where}"), params
    ).scalar() or 0

    return {
        "success": True,
        "data": {
            "total_tasks": total_capas,
            "completed_tasks": completed_capas,
            "active_permits": active_permits,
        }
    }


@router.get("/tasks/{id}")
def get_task(
    id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    # Try fetching from DB first
    if id.isdigit():
        r = db.execute(
            text("SELECT * FROM capa_actions WHERE id = :id AND organisation_id = :org_id"),
            {"id": int(id), "org_id": current_user.org_id}
        ).mappings().first()
        if r:
            task = {
                "id": str(r["id"]),
                "title": r["action_type"] or "Safety Compliance Action",
                "location": "Zone B - Sector 4",
                "priority": "high",
                "type": "checklist",
                "status": r["status"].lower() == "completed" and "completed" or "pending",
                "due_at": r["due_date"].isoformat() if r["due_date"] else None,
                "steps": [
                    { "id": "1", "title": r["description"] or "Check area compliance", "completed": r["status"].lower() == "completed" }
                ]
            }
            return {"success": True, "data": task}

    # Mock fallback
    return {
        "success": True,
        "data": {
            "id": id,
            "title": "Equipment Check: Main Excavator Hydraulics",
            "location": "Zone B - Sector 4",
            "priority": "high",
            "type": "checklist",
            "status": "pending",
            "due_at": date.today().isoformat() + "T16:00:00",
            "steps": [
                { "id": "1", "title": "Check hydraulic fluid levels", "completed": False },
                { "id": "2", "title": "Inspect high-pressure hoses for cracks", "completed": False }
            ]
        }
    }


@router.post("/tasks/{id}/complete-step")
def complete_task_step(
    id: str,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    if id.isdigit():
        db.execute(
            text("UPDATE capa_actions SET status = 'Completed' WHERE id = :id AND organisation_id = :org_id"),
            {"id": int(id), "org_id": current_user.org_id}
        )
        db.commit()
    return {"success": True, "data": {"id": id, "status": "completed"}}


# ─── Permits Endpoints ────────────────────────────────────────────────────────

@router.get("/permits")
def list_permits(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    query_str = """
        SELECT p.*, pt.permit_type_name as permit_type_name, ws.station_name as location_name,
               req.full_name AS requested_by_name
        FROM permits_to_work p
        LEFT JOIN permit_types pt ON p.permit_type_id = pt.id
        LEFT JOIN working_stations ws ON p.location_station_id = ws.id
        -- Resolved through the requester's *login* org, not the employee row's.
        -- The two disagree for most people in this database (employee 21 is
        -- org 1, his account is org 4) and the login is what determines the
        -- tenant somebody actually works in — the same reasoning
        -- services/capa_owners.py documents. Scoping on the employee row
        -- instead returned NULL for every permit here; dropping the scope
        -- entirely would name another tenant's staff.
        LEFT JOIN users req_u ON req_u.employee_id = p.requested_by
                             AND req_u.organisation_id = p.organisation_id
        LEFT JOIN employees req ON req.id = req_u.employee_id
        WHERE p.organisation_id = :org_id
    """
    params = {"org_id": current_user.org_id}

    # Scope to permits this worker raised or acknowledged (per-worker view).
    emp_id = _employee_id(db, current_user)
    if emp_id:
        query_str += " AND (p.requested_by = :emp_id OR p.acknowledged_by = :emp_id)"
        params["emp_id"] = emp_id

    if status:
        query_str += " AND p.status = :status"
        params["status"] = status

    rows = db.execute(text(query_str), params).mappings().all()

    items = []
    for r in rows:
        # Standardize permit types names to match frontend types
        pt_name = r["permit_type_name"] or "hot_work"
        pt_name_lower = pt_name.lower().replace(" ", "_")
        if pt_name_lower not in ["hot_work", "confined_space", "working_at_height", "electrical", "excavation"]:
            pt_name_lower = "hot_work"

        items.append({
            "id": str(r["id"]),
            "permit_ref": f"PTW-{r['id']:04d}",
            "permit_type": pt_name_lower,
            "work_location": r["location_name"] or "Zone B - Sector 4",
            "start_datetime": r["validity_start"].isoformat() if r["validity_start"] else date.today().isoformat() + "T08:00:00",
            "end_datetime": r["validity_end"].isoformat() if r["validity_end"] else date.today().isoformat() + "T16:00:00",
            "work_description": r["work_description"] or "",
            "status": r["status"].lower() if r["status"] else "pending_approval",
            # The permit's real workflow state and its position on the eight
            # stages. `status` above is the website's business field (Pending /
            # Active / Closed) and says nothing about the lifecycle, so the
            # worker's list could show a permit without showing how far along
            # it was. Derived, never stored — see services/workflow_stages.
            "workflow_status": r["workflow_status"],
            **{
                k: v for k, v in workflow_stages.describe("permit", r["workflow_status"]).items()
                if k in ("stage", "stage_number", "stage_label", "completed_stages", "total_stages")
            },
            # The actual requester. This was hardcoded to "Alex Safety" on every
            # row — a stub left in place after the endpoint started returning
            # real permits, so the worker's list attributed all of them to a
            # person who does not exist in this database.
            "requested_by": r["requested_by_name"] or "Unknown",
            "created_at": r["date_issued"].isoformat() if r["date_issued"] else date.today().isoformat(),
            # What the worker attached when they raised it. Read back so the
            # permit they can see is the one they actually sent.
            "evidence": json.loads(r["evidence_json"]) if r["evidence_json"] else [],
            "safety_gear": {
                "hard_hat": True,
                "gloves": True,
                "eye_protection": True,
                "respirator": False
            }
        })

    return {"success": True, "data": {"items": items, "total": len(items)}}


def _dt(value) -> Optional[datetime]:
    """Parse an ISO datetime the app may or may not have sent."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", ""))
    except ValueError:
        return None


@router.post("/permits")
async def create_permit(
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    """Raise a permit, with or without the risk assessment attached.

    Declared as `payload: dict` until now, which is JSON-only: the moment the
    app attached a file and switched to multipart, FastAPI saw a multipart body
    where it expected a model and answered 422 — the same failure
    `report_media` was written to end for near miss, unsafe act and risk. The
    attach box on the permit form never got as far as finding out, because it
    had no handler wired to it at all.
    """
    data, media_urls = await report_media.read_report_body(request, subdir="permits")
    data = report_media.merge_media(data, media_urls)
    
    # Look up permit type id or default
    pt_name = data.get("permit_type", "hot_work").replace("_", " ")
    pt_id = db.execute(
        text("SELECT id FROM permit_types WHERE permit_type_name LIKE :name LIMIT 1"),
        {"name": f"%{pt_name}%"}
    ).scalar() or 1

    # Look up location id or default
    loc_name = data.get("work_location", "Zone B - Sector 4")
    loc_id = db.execute(
        text("SELECT id FROM working_stations WHERE station_name LIKE :name LIMIT 1"),
        {"name": f"%{loc_name}%"}
    ).scalar() or 1

    # The worker raising the permit — stamped so it enters the permit workflow
    # (supervisor queue) as a proper `requested` entry, not an orphaned row.
    requester_emp_id = db.execute(
        text("SELECT employee_id FROM users WHERE id = :uid"),
        {"uid": current_user.user_id},
    ).scalar()

    # Insert into permits_to_work
    db.execute(
        text("""
            INSERT INTO permits_to_work (
                organisation_id, permit_type_id, date_issued, time_issued,
                location_station_id, work_description, duration_requested_hours,
                validity_start, validity_end, status,
                workflow_status, requested_by, requested_at, issued_by,
                evidence_json
            ) VALUES (
                :org_id, :permit_type_id, :date_issued, :time_issued,
                :location_station_id, :work_description, :duration,
                :validity_start, :validity_end, :status,
                'requested', :requested_by, :requested_at, :requested_by,
                :evidence
            )
        """),
        {
            "org_id": current_user.org_id,
            "permit_type_id": pt_id,
            "date_issued": date.today(),
            "time_issued": time(8, 0),
            "location_station_id": loc_id,
            "work_description": data.get("work_description", ""),
            "duration": data.get("duration_hours", 8),
            # A missing end date used to default to `datetime.now()`, which
            # produced a permit that had already expired at the moment it was
            # raised: /activate refuses outside the window, so it could never be
            # worked under and the expiry sweep would take it out of service on
            # its next pass. The requested duration is what the worker actually
            # asked for, so the window runs from the start for that long.
            "validity_start": _dt(data.get("start_datetime")) or datetime.now(),
            "validity_end": (
                _dt(data.get("end_datetime"))
                or (_dt(data.get("start_datetime")) or datetime.now())
                + timedelta(hours=int(data.get("duration_hours") or 8))
            ),
            # 'Pending', as permit_workflow writes it. This endpoint used to
            # write 'pending_approval', a value no other permit writer or reader
            # uses: the analytics aggregates count 'Active' and 'Pending', so a
            # permit raised from the worker app was invisible to all of them.
            "status": "Pending",
            "requested_by": requester_emp_id,
            "requested_at": datetime.now(),
            "evidence": json.dumps(data.get("photos") or []) if data.get("photos") else None,
        }
    )

    # Read the id from the connection that did the INSERT, before the commit.
    # `SELECT LAST_INSERT_ID()` after `db.commit()` runs on a connection the
    # session has already released, so it returned 0 — every permit raised from
    # the worker app came back as id "0" and reference "PTW-0000", and nothing
    # the app did next could address the permit it had just created.
    new_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()
    db.commit()

    created_permit = {
        "id": str(new_id),
        "permit_ref": f"PTW-{new_id:04d}",
        "permit_type": data.get("permit_type", "hot_work"),
        "work_location": data.get("work_location", "Zone B - Sector 4"),
        "start_datetime": data.get("start_datetime", date.today().isoformat() + "T08:00:00"),
        "end_datetime": data.get("end_datetime", date.today().isoformat() + "T16:00:00"),
        "work_description": data.get("work_description", ""),
        "status": "pending",
        "workflow_status": "requested",
        "evidence": data.get("photos") or [],
        "requested_by": "Alex Safety",
        "created_at": date.today().isoformat(),
        "safety_gear": data.get("safety_gear", {
            "hard_hat": True,
            "gloves": True,
            "eye_protection": True,
            "respirator": False
        })
    }

    return {"success": True, "data": created_permit}


@router.post("/permits/{id}/acknowledge")
def acknowledge_permit(
    id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    """The worker accepting an issued permit and starting work under it.

    This used to be a bare `UPDATE permits_to_work SET status = 'Active'` — no
    role check, no check that the caller had anything to do with the permit, no
    check of what state it was in, and no gate evaluation. `status='Active'` is
    the column six analytics aggregates read as "live work", so any signed-in
    account could mark any permit in the organisation as live: one that no
    manager had approved, one the gate engine had blocked for an expired
    competence certificate, one already rejected. It also left `status` and
    `workflow_status` contradicting each other, which the permit workflow is
    explicit about keeping in step.

    Accepting a permit *is* a real step — it is the holder taking it on and
    starting the job — and that step already exists as `/permit-workflow/{id}/activate`,
    with the guards this one was missing. So it delegates rather than writing:
    one state machine, one set of rules, whichever door the request arrives at.
    """
    if not id.isdigit():
        raise HTTPException(status_code=404, detail="No such permit")

    from app.controllers.permit_workflow import activate_permit

    row = activate_permit(int(id), db, current_user)
    return {
        "success": True,
        "data": {"id": id, "status": row.status, "workflow_status": row.workflow_status},
    }


@router.get("/my-kpis")
def get_my_kpis(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    """
    The spec's "Values Worker Gets" panel — everything scoped to the signed-in
    worker, not the org. Counts are for the current calendar month so the numbers
    reset with each reporting period.
    """
    emp_id = _employee_id(db, current_user)
    if not emp_id:
        today = date.today()
        return {
            "success": True,
            "data": {
                "my_incidents": 0, "my_near_misses": 0, "hours_logged_month": 0.0,
                "my_open_capa": 0, "incident_feed": [],
                "period_month": today.month, "period_year": today.year,
                "period_label": today.strftime("%B %Y"),
            },
        }

    # Anchor "this period" on the latest month this worker actually has data for,
    # not on today. With a historical dataset (org 4 ends Dec-2025) a today-anchored
    # month is always empty — the same reason dashboard.py anchors on the data window.
    anchor = db.execute(
        text("""
            SELECT MAX(d) FROM (
                SELECT MAX(shift_date) AS d FROM shift_schedule
                 WHERE organisation_id = :org_id AND employee_id = :emp_id
                UNION ALL
                SELECT MAX(incident_date_time) FROM incidents
                 WHERE organisation_id = :org_id AND reported_by = :emp_id
                UNION ALL
                SELECT MAX(event_date_time) FROM near_misses
                 WHERE organisation_id = :org_id AND reported_by = :emp_id
            ) AS x
        """),
        {"org_id": current_user.org_id, "emp_id": emp_id},
    ).scalar()

    period = anchor.date() if hasattr(anchor, "date") else (anchor or date.today())
    params = {
        "org_id": current_user.org_id,
        "emp_id": emp_id,
        "month": period.month,
        "year": period.year,
    }

    my_incidents = db.execute(
        text("""SELECT COUNT(*) FROM incidents
                WHERE organisation_id = :org_id AND reported_by = :emp_id
                  AND MONTH(incident_date_time) = :month AND YEAR(incident_date_time) = :year"""),
        params,
    ).scalar() or 0

    my_near_misses = db.execute(
        text("""SELECT COUNT(*) FROM near_misses
                WHERE organisation_id = :org_id AND reported_by = :emp_id
                  AND MONTH(event_date_time) = :month AND YEAR(event_date_time) = :year"""),
        params,
    ).scalar() or 0

    hours = db.execute(
        text("""SELECT COALESCE(SUM(actual_hours_worked), 0) FROM shift_schedule
                WHERE organisation_id = :org_id AND employee_id = :emp_id
                  AND MONTH(shift_date) = :month AND YEAR(shift_date) = :year"""),
        params,
    ).scalar() or 0

    my_open_capa = db.execute(
        text("""SELECT COUNT(*) FROM capa_actions
                WHERE organisation_id = :org_id AND responsible_person_id = :emp_id
                  AND status <> 'Completed'"""),
        {"org_id": current_user.org_id, "emp_id": emp_id},
    ).scalar() or 0

    # Status feed for the incidents this worker raised, newest first.
    feed_rows = db.execute(
        text("""SELECT id, incident_type, workflow_status, acknowledged_at,
                       investigation_status, incident_date_time
                FROM incidents
                WHERE organisation_id = :org_id AND reported_by = :emp_id
                ORDER BY incident_date_time DESC LIMIT 10"""),
        {"org_id": current_user.org_id, "emp_id": emp_id},
    ).mappings().all()

    return {
        "success": True,
        "data": {
            "my_incidents": my_incidents,
            "my_near_misses": my_near_misses,
            "hours_logged_month": float(hours),
            "my_open_capa": my_open_capa,
            # The month these counts cover — the anchor is data-driven, so it is
            # often not the current calendar month. The UI labels the panel with it
            # instead of letting "Your Month" imply today.
            "period_month": period.month,
            "period_year": period.year,
            "period_label": period.strftime("%B %Y"),
            "incident_feed": [
                {
                    "id": r["id"],
                    "reference": f"INC-{r['id']}",
                    "incident_type": r["incident_type"],
                    "workflow_status": r["workflow_status"],
                    "acknowledged": r["acknowledged_at"] is not None,
                    "investigation_complete": str(r["investigation_status"] or "").lower() == "completed",
                    "occurred_at": r["incident_date_time"].isoformat() if r["incident_date_time"] else None,
                }
                for r in feed_rows
            ],
        },
    }


# ─── Shift Check-In Endpoints ─────────────────────────────────────────────────

@router.get("/shift/my-shifts")
def list_my_shifts(
    limit: int = Query(30, le=1000),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    """Recent shift records for the signed-in worker, newest first."""
    emp_id = _employee_id(db, current_user)
    if not emp_id:
        return {"success": True, "data": []}

    rows = db.execute(
        text("""
            SELECT s.id, s.shift_date, s.shift_type, s.shift_start, s.shift_end,
                   s.actual_hours_worked, s.station_id, s.supervisor_id,
                   ws.station_name
            FROM shift_schedule s
            LEFT JOIN working_stations ws ON ws.id = s.station_id
            WHERE s.organisation_id = :org_id AND s.employee_id = :emp_id
            ORDER BY s.shift_date DESC, s.id DESC
            LIMIT :limit
        """),
        {"org_id": current_user.org_id, "emp_id": emp_id, "limit": limit}
    ).mappings().all()

    return {
        "success": True,
        "data": [
            {
                "id": r["id"],
                "shift_date": str(r["shift_date"]) if r["shift_date"] else None,
                "shift_type": r["shift_type"],
                "shift_start": str(r["shift_start"]) if r["shift_start"] else None,
                "shift_end": str(r["shift_end"]) if r["shift_end"] else None,
                "actual_hours_worked": float(r["actual_hours_worked"]) if r["actual_hours_worked"] is not None else None,
                "station_id": r["station_id"],
                "station_name": r["station_name"],
                "confirmed": r["supervisor_id"] is not None,
            }
            for r in rows
        ],
    }


@router.post("/shift/check-in")
def shift_check_in(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    """
    Logs the hours a worker actually worked. This is the man-hours denominator for
    TRIR / LTIFR / LTISR / DART / FAR — without it those rates have nothing to divide by.

    Re-checking in for a date the worker already logged updates that row instead of
    creating a duplicate, so hours can be corrected at end of shift.
    """
    data = payload.get("data", payload)

    emp_id = _employee_id(db, current_user)
    if not emp_id:
        raise HTTPException(status_code=400, detail="No employee record is linked to this account")

    shift_date = data.get("shift_date") or date.today().isoformat()
    try:
        hours = float(data.get("actual_hours_worked"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="actual_hours_worked is required and must be a number")
    if hours <= 0 or hours > 24:
        raise HTTPException(status_code=400, detail="actual_hours_worked must be between 0 and 24")

    params = {
        "org_id": current_user.org_id,
        "emp_id": emp_id,
        "shift_date": shift_date,
        "shift_type": data.get("shift_type") or "Morning",
        "shift_start": data.get("shift_start") or None,
        "shift_end": data.get("shift_end") or None,
        "hours": hours,
        "station_id": data.get("station_id") or None,
    }

    existing = db.execute(
        text("""
            SELECT id FROM shift_schedule
            WHERE organisation_id = :org_id AND employee_id = :emp_id AND shift_date = :shift_date
        """),
        {"org_id": current_user.org_id, "emp_id": emp_id, "shift_date": shift_date}
    ).mappings().first()

    if existing:
        params["id"] = existing["id"]
        db.execute(
            text("""
                UPDATE shift_schedule
                SET shift_type = :shift_type, shift_start = :shift_start, shift_end = :shift_end,
                    actual_hours_worked = :hours, station_id = :station_id
                WHERE id = :id
            """),
            params
        )
        shift_id = existing["id"]
    else:
        db.execute(
            text("""
                INSERT INTO shift_schedule (
                    organisation_id, employee_id, shift_date, shift_type,
                    shift_start, shift_end, actual_hours_worked, station_id
                ) VALUES (
                    :org_id, :emp_id, :shift_date, :shift_type,
                    :shift_start, :shift_end, :hours, :station_id
                )
            """),
            params
        )
        shift_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()

    db.commit()
    return {"success": True, "data": {"id": shift_id, "shift_date": shift_date, "actual_hours_worked": hours}}


# ─── Incidents Endpoints ──────────────────────────────────────────────────────

async def _body_and_photos(request: Request) -> tuple[dict, list[str]]:
    """Read the report body, whether it arrived as JSON or as multipart.

    Thin alias over the shared reader in `app.utils.report_media`, which the
    factory-built families use too. It used to be implemented here, which is how
    this endpoint came to accept attached files while near miss, unsafe act and
    risk did not.
    """
    return await report_media.read_report_body(request)


@router.post("/incidents")
async def report_incident(
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    require_valid_org(current_user)
    data, photo_urls = await _body_and_photos(request)

    # Find employee linked to this user
    user_row = db.execute(
        text("SELECT employee_id FROM users WHERE id = :uid"),
        {"uid": current_user.user_id}
    ).mappings().first()

    emp_id = user_row["employee_id"] if user_row else None

    import json

    # Resolve working station: prefer an explicit FK, fall back to name lookup so
    # older clients that only send a station name keep working.
    loc_id = data.get("location_station_id")
    if not loc_id:
        loc_name = data.get("location", "Heavy Assembly Station 1")
        loc_row = db.execute(
            text("SELECT id FROM working_stations WHERE station_name = :name AND organisation_id = :org_id"),
            {"name": loc_name, "org_id": current_user.org_id}
        ).mappings().first()
        loc_id = loc_row["id"] if loc_row else 1

    # incident_date_time is what every rate KPI buckets on, so honour the value the
    # reporter picked instead of stamping "now".
    incident_dt = datetime.now()
    raw_dt = data.get("incident_date_time")
    if raw_dt:
        try:
            incident_dt = datetime.fromisoformat(str(raw_dt).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass

    def _yes_no(key: str, default: str = "No") -> str:
        val = str(data.get(key, default) or default).strip().lower()
        return "Yes" if val in ("yes", "true", "1") else "No"

    # Mobile never sends this field, so it defaults to "Mobile App" for every
    # caller today — the web registration form is the one caller that passes
    # "Web App" explicitly. Whitelisted rather than trusting the raw string:
    # this column drives the Incidents page's source filter (item #16), and a
    # typo'd value would just silently stop matching that filter forever.
    source = data.get("source")
    if source not in ("Mobile App", "Web App", "Data Import"):
        source = "Mobile App"

    # Save to incidents table
    db.execute(
        text("""
            INSERT INTO incidents (
                organisation_id, report_date, incident_date_time, location_station_id, incident_type,
                severity, description, immediate_cause, number_persons_involved, anyone_injured,
                injured_person_name, injured_body_part, hazard_id, permit_active, control_failure,
                hazard_still_present, immediate_actions_taken, witnesses_json, evidence_json,
                gps_latitude, gps_longitude, investigation_status, reported_by, workflow_status,
                reported_at, source, assigned_supervisor_id
            ) VALUES (
                :org_id, :report_date, :incident_date_time, :loc_id, :incident_type,
                :severity, :description, :immediate_cause, :number_persons_involved, :anyone_injured,
                :injured_person_name, :injured_body_part, :hazard_id, :permit_active, :control_failure,
                :hazard_still_present, :immediate_actions_taken, :witnesses_json, :evidence_json,
                :gps_latitude, :gps_longitude, :investigation_status, :reported_by, :workflow_status,
                :reported_at, :source, :assigned_supervisor_id
            )
        """),
        {
            "org_id": current_user.org_id,
            # Routed the same way /incident-workflow/report routes it: the
            # reporter's manager, else a supervisor in their own department,
            # else nobody. This endpoint is the one the mobile app and the web
            # register page actually post to, and it used to assign no
            # supervisor at all -- so where an incident landed depended on
            # which door it came through.
            "assigned_supervisor_id": supervisor_routing.find_supervisor_for(db, current_user),
            "report_date": incident_dt.date(),
            "incident_date_time": incident_dt,
            "loc_id": loc_id,
            "incident_type": data.get("incident_type", "Injury"),
            "severity": data.get("severity", "Minor"),
            "description": data.get("description", ""),
            "immediate_cause": data.get("immediate_cause", data.get("reason", "")),
            "number_persons_involved": data.get("number_persons_involved") or None,
            "anyone_injured": _yes_no("anyone_injured"),
            "injured_person_name": data.get("injured_person_name") or None,
            "injured_body_part": data.get("injured_body_part") or None,
            "hazard_id": data.get("hazard_id") or None,
            "permit_active": _yes_no("permit_active"),
            "control_failure": _yes_no("control_failure"),
            "hazard_still_present": _yes_no("hazard_still_present"),
            "immediate_actions_taken": data.get("immediate_actions_taken") or None,
            "witnesses_json": json.dumps(data.get("witnesses", [])),
            # Real uploaded images win. `photos`/`mockPhotos` in the JSON body
            # are the older clients' shape — a list of bare filenames that point
            # at nothing — so they are only used when nothing was actually
            # uploaded.
            "evidence_json": json.dumps(
                photo_urls or data.get("photos") or data.get("mockPhotos") or []
            ),
            "gps_latitude": data.get("gps_latitude"),
            "gps_longitude": data.get("gps_longitude"),
            "investigation_status": "open",
            "reported_by": emp_id,
            "workflow_status": "reported",
            "reported_at": datetime.now(),
            "source": source,
        }
    )
    # Read the id before committing — after a commit the SELECT can land on a
    # different pooled connection and return an unrelated LAST_INSERT_ID().
    new_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()

    # ── WF-03 · classify before committing ───────────────────────────────────
    # This is the endpoint the mobile app actually posts to (worker
    # ReportIncidentScreen -> ENDPOINTS.INCIDENTS.REPORT). The parallel
    # /incident-workflow/report route classifies too, but nothing calls it, so
    # without this every incident raised from the app was landing unclassified:
    # no P1-P5, no investigation SLA, no statutory obligation.
    #
    # The form does not yet collect the decision tree's Q2-Q4 inputs, so they
    # are read from the payload when a client sends them and otherwise left
    # unset — an injury with no treatment level classifies as "unclassified"
    # and escalates, which is the correct fail-safe.
    from app.controllers.incident_workflow import _apply_severity_and_statutory
    from app.models.incident import Incident

    incident_row = db.query(Incident).filter(Incident.id == new_id).first()
    if incident_row is not None:
        _apply_severity_and_statutory(
            db, incident_row,
            treatment_level=data.get("treatment_level"),
            # bool(...), not the raw payload value: these two are Yes/No
            # strings on the wire, and bool("No") is True — every submission
            # that answered "No" was being classified as if it had answered
            # "Yes" here. _yes_no is the same "yes"/"true"/"1" normaliser the
            # other Yes/No fields on this endpoint already go through.
            dangerous_occurrence=_yes_no("dangerous_occurrence") == "Yes" if "dangerous_occurrence" in data else None,
            worst_case_fatal=_yes_no("worst_case_fatal") == "Yes" if "worst_case_fatal" in data else None,
            days_away=data.get("days_away"),
        )

    # ── INCIDENT -> B · WF-01 ────────────────────────────────────────────────
    # Something happened, so the assessment covering this area was wrong. A
    # hazard report says an assessment may have missed something; an incident
    # says it did — so this reopens rather than flags, and carries the spec's
    # 48-hour deadline. Any permit relying on that assessment now fails its
    # gate, which is the point: work does not continue under an authorisation
    # the event has just disproved.
    from app.services import risk_assessment as risk_assessment_svc

    covering = risk_assessment_svc.covering_assessment(
        db, current_user.org_id,
        station_id=incident_row.location_station_id if incident_row else None,
    )
    if covering is not None:
        risk_assessment_svc.reopen_for_incident(
            db, covering,
            f"Incident INC-{new_id} occurred in this area — reassess within 48 hours",
            commit=False,
        )

    db.commit()

    return {
        "success": True,
        "data": {
            "id": str(new_id),
            "status": "submitted",
            # Returned so the app can show the classification straight after
            # submit rather than making the worker wait for a supervisor.
            "severity_priority": incident_row.severity_priority if incident_row else None,
            "severity_label": incident_row.severity_label if incident_row else None,
            "investigation_due_at": (
                incident_row.investigation_due_at.isoformat()
                if incident_row is not None and incident_row.investigation_due_at else None
            ),
            "statutory_reportable": bool(incident_row.statutory_reportable) if incident_row else False,
        },
    }


@router.get("/incidents")
def list_driver_incidents(
    mine: bool = False,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    # By default all org incidents; mine=true → only ones this worker reported.
    where = "i.organisation_id = :org_id"
    params = {"org_id": current_user.org_id}
    if mine:
        params["emp"] = _employee_id(db, current_user)
        where += " AND i.reported_by = :emp"

    rows = db.execute(
        text(f"""
            SELECT i.*, ws.station_name as location_name
            FROM incidents i
            LEFT JOIN working_stations ws ON i.location_station_id = ws.id
            WHERE {where}
            ORDER BY i.id DESC
        """),
        params
    ).mappings().all()
    
    items = []
    for r in rows:
        items.append({
            "id": str(r["id"]),
            "incident_type": r["incident_type"] or "injury",
            "severity": r["severity"] or "medium",
            "description": r["description"] or "",
            "location": r["location_name"] or "Zone B - Sector 4",
            "status": r["workflow_status"] or "reported",
            "created_at": r["created_at"].isoformat() if r["created_at"] else datetime.now().isoformat(),
            "incident_ref": f"INC-{r['id']}"
        })
        
    return {"success": True, "data": {"items": items, "total": len(items)}}


# ─── Checklists Endpoints ─────────────────────────────────────────────────────

@router.get("/checklists")
def list_checklists() -> dict:
    # Return checklists matching the templates
    return {"success": True, "data": {"items": []}}


@router.post("/checklists/{id}/submit")
def submit_checklist(id: str, payload: dict) -> dict:
    return {"success": True, "data": {"submission_id": "sub_check_" + id, "status": "success"}}


# ─── Notifications Endpoints ──────────────────────────────────────────────────

@router.get("/notifications")
def list_notifications(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    rows = db.execute(
        text("SELECT * FROM notifications WHERE organisation_id = :org_id ORDER BY id DESC LIMIT 20"),
        {"org_id": current_user.org_id}
    ).mappings().all()

    items = []
    for r in rows:
        items.append({
            "id": str(r["id"]),
            "title": r["title"] or "Safety Notification",
            "message": r["message"] or "",
            "type": r["type"].lower() if r["type"] else "info",
            "read": str(r["status"] or "").lower() in ("read", "seen"),
            "created_at": r["created_at"].isoformat() if r["created_at"] else datetime.now().isoformat()
        })

    if not items:
        items = [
            {
                "id": "n1",
                "title": "New Work Permit Approved",
                "message": "Permit for Welding in Maintenance Bay 4 has been approved.",
                "type": "success",
                "read": False,
                "created_at": datetime.now().isoformat()
            }
        ]

    return {"success": True, "data": {"items": items, "total": len(items)}}

# Training is now served by app.controllers.training_video (GET /training-videos/mine),
# which replaces this stub with real videos, descriptions, and per-role targeting.
