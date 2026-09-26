"""
Supervisor-assigned tasks with per-task custom checklists.

Flow:
  - Supervisor creates a task (title/desc/location/priority/due) + custom checklist
    items, and assigns it to one or more workers.
  - Each worker fills their own copy (Yes/No + description per item).
  - Manager sees every task (who assigned it, to whom, how many filled) and can
    edit the checklist. Supervisor + Manager both see the filled responses.
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser

router = APIRouter(prefix="/assigned-tasks", tags=["Assigned Tasks"])


# ── Role / identity helpers ───────────────────────────────────────────────────
def _employee_id(db: Session, user: CurrentUser):
    return db.execute(
        text("SELECT employee_id FROM users WHERE id = :uid"), {"uid": user.user_id}
    ).scalar()


def _role(user: CurrentUser) -> str:
    return (user.role or "").lower()


def _is_manager(user: CurrentUser) -> bool:
    r = _role(user)
    return "manager" in r or r in ("admin", "safety_manager", "hse_manager")


def _is_supervisor(user: CurrentUser) -> bool:
    return "supervisor" in _role(user)


def _emp_name(db: Session, emp_id) -> Optional[str]:
    if not emp_id:
        return None
    return db.execute(
        text("SELECT full_name FROM employees WHERE id = :id"), {"id": emp_id}
    ).scalar()


# ── Assignable workers (for the supervisor's picker) ──────────────────────────
@router.get("/assignable-workers")
def assignable_workers(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Active *workers* in the org the supervisor can assign a task to.

    Tasks are assigned to workers, so only employees whose login carries the
    'operator' (worker) role are listed — managers, supervisors and auditors are
    excluded even though they also have employee records.
    """
    rows = db.execute(
        text(
            "SELECT e.id, e.full_name, d.department_name AS department "
            "FROM employees e "
            "JOIN users u ON u.employee_id = e.id "
            "JOIN app_roles ar ON ar.id = u.app_role_id "
            "LEFT JOIN departments d ON e.department_id = d.id "
            "WHERE e.organisation_id = :org "
            "AND (e.active_status IS NULL OR e.active_status = 'Active') "
            "AND LOWER(ar.name) = 'operator' "
            "ORDER BY e.full_name"
        ),
        {"org": current_user.org_id},
    ).mappings().all()
    return {
        "success": True,
        "data": [
            {"employee_id": r["id"], "name": r["full_name"], "department": r["department"] or ""}
            for r in rows
        ],
    }


# ── Create a task (supervisor) ────────────────────────────────────────────────
@router.post("")
def create_task(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    data = payload.get("data", payload)
    title = (data.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Task title is required")

    items = data.get("items") or []
    worker_ids = data.get("worker_ids") or []
    if not items:
        raise HTTPException(status_code=400, detail="At least one checklist item is required")
    if not worker_ids:
        raise HTTPException(status_code=400, detail="Assign the task to at least one worker")

    due_at = None
    if data.get("due_at"):
        try:
            due_at = datetime.fromisoformat(str(data["due_at"]).replace("Z", ""))
        except ValueError:
            due_at = None

    assigned_by = _employee_id(db, current_user)

    db.execute(
        text(
            "INSERT INTO assigned_tasks "
            "(organisation_id, title, description, location, priority, due_at, assigned_by, status) "
            "VALUES (:org, :title, :desc, :loc, :prio, :due, :by, 'active')"
        ),
        {
            "org": current_user.org_id,
            "title": title,
            "desc": data.get("description") or "",
            "loc": data.get("location") or "",
            "prio": (data.get("priority") or "medium").lower(),
            "due": due_at,
            "by": assigned_by,
        },
    )
    task_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()

    for i, it in enumerate(items, start=1):
        item_text = (it.get("item_text") if isinstance(it, dict) else str(it)) or ""
        item_text = item_text.strip()
        if not item_text:
            continue
        db.execute(
            text(
                "INSERT INTO assigned_task_items (task_id, item_no, item_text, is_required) "
                "VALUES (:tid, :no, :txt, :req)"
            ),
            {
                "tid": task_id,
                "no": i,
                "txt": item_text,
                "req": 1 if (not isinstance(it, dict) or it.get("is_required", True)) else 0,
            },
        )

    for wid in worker_ids:
        db.execute(
            text(
                "INSERT INTO assigned_task_workers (task_id, worker_employee_id, status) "
                "VALUES (:tid, :wid, 'pending')"
            ),
            {"tid": task_id, "wid": int(wid)},
        )

    db.commit()
    return {"success": True, "data": {"id": task_id, "title": title}}


# ── List tasks (role-aware) ───────────────────────────────────────────────────
@router.get("")
def list_tasks(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    emp_id = _employee_id(db, current_user)
    params = {"org": current_user.org_id}
    where = "t.organisation_id = :org"

    if _is_manager(current_user):
        pass  # manager sees every task in the org
    elif _is_supervisor(current_user):
        where += " AND t.assigned_by = :emp"
        params["emp"] = emp_id
    else:
        # worker — only tasks assigned to them
        where += " AND t.id IN (SELECT task_id FROM assigned_task_workers WHERE worker_employee_id = :emp)"
        params["emp"] = emp_id

    rows = db.execute(
        text(
            f"SELECT t.*, e.full_name AS assigned_by_name "
            f"FROM assigned_tasks t LEFT JOIN employees e ON t.assigned_by = e.id "
            f"WHERE {where} ORDER BY t.created_at DESC"
        ),
        params,
    ).mappings().all()

    out = []
    for t in rows:
        counts = db.execute(
            text(
                "SELECT COUNT(*) AS total, SUM(status='filled') AS filled "
                "FROM assigned_task_workers WHERE task_id = :tid"
            ),
            {"tid": t["id"]},
        ).mappings().first()
        item = {
            "id": t["id"],
            "title": t["title"],
            "description": t["description"] or "",
            "location": t["location"] or "",
            "priority": t["priority"],
            "due_at": t["due_at"].isoformat() if t["due_at"] else None,
            "status": t["status"],
            "created_at": t["created_at"].isoformat() if t["created_at"] else None,
            "assigned_by_id": t["assigned_by"],
            "assigned_by_name": t["assigned_by_name"] or "Supervisor",
            "worker_count": int(counts["total"] or 0),
            "filled_count": int(counts["filled"] or 0),
        }
        if not _is_manager(current_user) and not _is_supervisor(current_user):
            mine = db.execute(
                text(
                    "SELECT status FROM assigned_task_workers "
                    "WHERE task_id = :tid AND worker_employee_id = :emp"
                ),
                {"tid": t["id"], "emp": emp_id},
            ).scalar()
            item["my_status"] = mine or "pending"
        out.append(item)

    return {"success": True, "data": {"items": out, "total": len(out)}}


# ── Task detail (items + assigned workers) ────────────────────────────────────
@router.get("/{task_id}")
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    t = db.execute(
        text(
            "SELECT t.*, e.full_name AS assigned_by_name FROM assigned_tasks t "
            "LEFT JOIN employees e ON t.assigned_by = e.id "
            "WHERE t.id = :tid AND t.organisation_id = :org"
        ),
        {"tid": task_id, "org": current_user.org_id},
    ).mappings().first()
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")

    items = db.execute(
        text(
            "SELECT id, item_no, item_text, is_required FROM assigned_task_items "
            "WHERE task_id = :tid ORDER BY item_no"
        ),
        {"tid": task_id},
    ).mappings().all()

    workers = db.execute(
        text(
            "SELECT w.worker_employee_id AS employee_id, e.full_name AS name, w.status, w.filled_at "
            "FROM assigned_task_workers w LEFT JOIN employees e ON w.worker_employee_id = e.id "
            "WHERE w.task_id = :tid ORDER BY e.full_name"
        ),
        {"tid": task_id},
    ).mappings().all()

    # The requesting worker's own answers so far (for prefill when re-opening).
    emp_id = _employee_id(db, current_user)
    my_status = None
    my_responses = {}
    if emp_id:
        row = db.execute(
            text("SELECT status FROM assigned_task_workers WHERE task_id = :tid AND worker_employee_id = :emp"),
            {"tid": task_id, "emp": emp_id},
        ).scalar()
        my_status = row
        resp = db.execute(
            text("SELECT item_id, answer, description FROM assigned_task_responses "
                 "WHERE task_id = :tid AND worker_employee_id = :emp"),
            {"tid": task_id, "emp": emp_id},
        ).mappings().all()
        my_responses = {r["item_id"]: {"answer": r["answer"], "description": r["description"] or ""} for r in resp}

    return {
        "success": True,
        "data": {
            "id": t["id"],
            "title": t["title"],
            "description": t["description"] or "",
            "location": t["location"] or "",
            "priority": t["priority"],
            "due_at": t["due_at"].isoformat() if t["due_at"] else None,
            "status": t["status"],
            "assigned_by_id": t["assigned_by"],
            "assigned_by_name": t["assigned_by_name"] or "Supervisor",
            "items": [
                {"id": it["id"], "item_no": it["item_no"], "item_text": it["item_text"],
                 "is_required": bool(it["is_required"])}
                for it in items
            ],
            "workers": [
                {"employee_id": w["employee_id"], "name": w["name"] or f"Worker {w['employee_id']}",
                 "status": w["status"], "filled_at": w["filled_at"].isoformat() if w["filled_at"] else None}
                for w in workers
            ],
            "my_status": my_status,
            "my_responses": my_responses,
        },
    }


# ── Worker fills their checklist (Yes/No + description per item) ───────────────
@router.post("/{task_id}/fill")
def fill_task(
    task_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    emp_id = _employee_id(db, current_user)
    if not emp_id:
        raise HTTPException(status_code=400, detail="No employee is linked to your account")

    assigned = db.execute(
        text("SELECT id FROM assigned_task_workers WHERE task_id = :tid AND worker_employee_id = :emp"),
        {"tid": task_id, "emp": emp_id},
    ).scalar()
    if not assigned:
        raise HTTPException(status_code=403, detail="This task is not assigned to you")

    data = payload.get("data", payload)
    responses = data.get("responses") or []

    for r in responses:
        item_id = r.get("item_id")
        if not item_id:
            continue
        db.execute(
            text(
                "INSERT INTO assigned_task_responses (task_id, worker_employee_id, item_id, answer, description) "
                "VALUES (:tid, :emp, :iid, :ans, :desc) "
                "ON DUPLICATE KEY UPDATE answer = VALUES(answer), description = VALUES(description)"
            ),
            {
                "tid": task_id,
                "emp": emp_id,
                "iid": int(item_id),
                "ans": r.get("answer"),
                "desc": r.get("description") or "",
            },
        )

    db.execute(
        text(
            "UPDATE assigned_task_workers SET status = 'filled', filled_at = :now "
            "WHERE task_id = :tid AND worker_employee_id = :emp"
        ),
        {"now": datetime.now(), "tid": task_id, "emp": emp_id},
    )
    db.commit()
    return {"success": True, "data": {"task_id": task_id, "status": "filled"}}


# ── All workers' filled responses (manager + supervisor) ──────────────────────
@router.get("/{task_id}/responses")
def task_responses(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    if not (_is_manager(current_user) or _is_supervisor(current_user)):
        raise HTTPException(status_code=403, detail="Only managers/supervisors can view responses")

    t = db.execute(
        text("SELECT t.*, e.full_name AS assigned_by_name FROM assigned_tasks t "
             "LEFT JOIN employees e ON t.assigned_by = e.id "
             "WHERE t.id = :tid AND t.organisation_id = :org"),
        {"tid": task_id, "org": current_user.org_id},
    ).mappings().first()
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")

    items = db.execute(
        text("SELECT id, item_no, item_text, is_required FROM assigned_task_items "
             "WHERE task_id = :tid ORDER BY item_no"),
        {"tid": task_id},
    ).mappings().all()

    workers = db.execute(
        text("SELECT w.worker_employee_id AS employee_id, e.full_name AS name, w.status, w.filled_at "
             "FROM assigned_task_workers w LEFT JOIN employees e ON w.worker_employee_id = e.id "
             "WHERE w.task_id = :tid ORDER BY e.full_name"),
        {"tid": task_id},
    ).mappings().all()

    worker_blocks = []
    for w in workers:
        resp = db.execute(
            text("SELECT item_id, answer, description FROM assigned_task_responses "
                 "WHERE task_id = :tid AND worker_employee_id = :emp"),
            {"tid": task_id, "emp": w["employee_id"]},
        ).mappings().all()
        worker_blocks.append({
            "employee_id": w["employee_id"],
            "name": w["name"] or f"Worker {w['employee_id']}",
            "status": w["status"],
            "filled_at": w["filled_at"].isoformat() if w["filled_at"] else None,
            "responses": {r["item_id"]: {"answer": r["answer"], "description": r["description"] or ""} for r in resp},
        })

    return {
        "success": True,
        "data": {
            "id": t["id"],
            "title": t["title"],
            "description": t["description"] or "",
            "location": t["location"] or "",
            "priority": t["priority"],
            "due_at": t["due_at"].isoformat() if t["due_at"] else None,
            "assigned_by_name": t["assigned_by_name"] or "Supervisor",
            "items": [
                {"id": it["id"], "item_no": it["item_no"], "item_text": it["item_text"],
                 "is_required": bool(it["is_required"])}
                for it in items
            ],
            "workers": worker_blocks,
        },
    }


# ── Manager edits the checklist items ─────────────────────────────────────────
@router.put("/{task_id}/items")
def edit_items(
    task_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    if not _is_manager(current_user):
        raise HTTPException(status_code=403, detail="Only managers can edit the checklist")

    t = db.execute(
        text("SELECT id FROM assigned_tasks WHERE id = :tid AND organisation_id = :org"),
        {"tid": task_id, "org": current_user.org_id},
    ).scalar()
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")

    data = payload.get("data", payload)
    items = data.get("items") or []
    clean = [it for it in items if (it.get("item_text") or "").strip()]
    if not clean:
        raise HTTPException(status_code=400, detail="At least one checklist item is required")

    existing_ids = {
        r for (r,) in db.execute(
            text("SELECT id FROM assigned_task_items WHERE task_id = :tid"), {"tid": task_id}
        ).all()
    }
    kept_ids = set()

    for i, it in enumerate(clean, start=1):
        item_text = it["item_text"].strip()
        required = 1 if it.get("is_required", True) else 0
        iid = it.get("id")
        if iid and int(iid) in existing_ids:
            db.execute(
                text("UPDATE assigned_task_items SET item_text = :txt, is_required = :req, item_no = :no "
                     "WHERE id = :id AND task_id = :tid"),
                {"txt": item_text, "req": required, "no": i, "id": int(iid), "tid": task_id},
            )
            kept_ids.add(int(iid))
        else:
            db.execute(
                text("INSERT INTO assigned_task_items (task_id, item_no, item_text, is_required) "
                     "VALUES (:tid, :no, :txt, :req)"),
                {"tid": task_id, "no": i, "txt": item_text, "req": required},
            )

    # Delete removed items (and any responses tied to them).
    removed = existing_ids - kept_ids
    for rid in removed:
        db.execute(text("DELETE FROM assigned_task_responses WHERE item_id = :id"), {"id": rid})
        db.execute(text("DELETE FROM assigned_task_items WHERE id = :id"), {"id": rid})

    db.commit()
    return {"success": True, "data": {"task_id": task_id, "item_count": len(clean)}}
