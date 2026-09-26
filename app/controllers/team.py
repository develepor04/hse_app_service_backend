"""
Hierarchical team provisioning (mobile):
  - HSE Manager adds Supervisors
  - Supervisor adds Workers (operators)

Each add creates BOTH a login user (users, with the right app_role) AND an
employee HR record (employees, linked via users.employee_id), then emails an
invite with a temporary password — same mechanism the org-admin invite uses.
"""

import re
import secrets
import string

import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.config.settings import get_settings
from app.core.dependencies import get_current_user, CurrentUser
from app.services.email_service import send_email, _build_invite_html
from app.utils.logger import get_logger

router = APIRouter(prefix="/team", tags=["Team Provisioning"])
settings = get_settings()
logger = get_logger(__name__)

_ALPHABET = string.ascii_letters + string.digits + "!@#$%"


# ── Role helpers (JWT role is lowercase: safety_manager / supervisor / operator) ─
def _is_manager(u: CurrentUser) -> bool:
    r = (u.role or "").lower()
    return "manager" in r or r in ("admin", "safety_manager", "hse_manager")


def _is_supervisor(u: CurrentUser) -> bool:
    return "supervisor" in (u.role or "").lower()


def _employee_id(db: Session, u: CurrentUser):
    return db.execute(
        text("SELECT employee_id FROM users WHERE id = :id"), {"id": u.user_id}
    ).scalar()


def _role_id(db: Session, name: str) -> int:
    rid = db.execute(text("SELECT id FROM app_roles WHERE name = :n"), {"n": name}).scalar()
    if not rid:
        raise HTTPException(status_code=400, detail=f"Role '{name}' is not configured")
    return rid


def _gen_password(length: int = 12) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def _create_member(db, current_user, name, email, role_name, department_id, manager_emp_id):
    name = (name or "").strip()
    email = (email or "").strip().lower()
    if not name or not email:
        raise HTTPException(status_code=400, detail="Name and email are required")
    if db.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email}).scalar():
        raise HTTPException(status_code=409, detail=f"A user with email {email} already exists")

    org_id = current_user.org_id
    app_role_id = _role_id(db, role_name)

    # 1) Employee HR record
    db.execute(
        text("INSERT INTO employees (full_name, organisation_id, department_id, manager_id, "
             "employment_type, active_status) "
             "VALUES (:n, :org, :dept, :mgr, 'Full-time', 'Active')"),
        {"n": name, "org": org_id, "dept": department_id, "mgr": manager_emp_id},
    )
    emp_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()

    # 2) Login user (unique username from email local-part)
    base = re.sub(r"[^a-z0-9_]", "_", email.split("@")[0].lower())
    username, i = base, 1
    while db.execute(text("SELECT id FROM users WHERE username = :u"), {"u": username}).scalar():
        username = f"{base}_{i}"; i += 1

    temp_password = _gen_password()
    pw_hash = bcrypt.hashpw(temp_password.encode(), bcrypt.gensalt()).decode()

    db.execute(
        text("INSERT INTO users (username, full_name, email, password_hash, app_role_id, "
             "employee_id, organisation_id, is_active) "
             "VALUES (:u, :n, :e, :ph, :rid, :emp, :org, 1)"),
        {"u": username, "n": name, "e": email, "ph": pw_hash,
         "rid": app_role_id, "emp": emp_id, "org": org_id},
    )
    user_id = db.execute(text("SELECT LAST_INSERT_ID()")).scalar()
    db.commit()

    # 3) Invite email (non-fatal if SMTP is unavailable — temp password is returned too)
    org_name = db.execute(
        text("SELECT organisation_name FROM organisation WHERE id = :id"), {"id": org_id}
    ).scalar() or "your organisation"
    login_url = f"{settings.frontend_url}/auth/login"
    sent = False
    try:
        html = _build_invite_html(admin_name=name, organisation_name=org_name,
                                  email=email, temp_password=temp_password, login_url=login_url)
        sent = send_email(to_email=email,
                          subject=f"You've been invited to {org_name} — EHSERA Intelligence",
                          html_content=html, to_name=name)
    except Exception as e:  # noqa: BLE001
        logger.warning("Invite email failed for %s: %s", email, e)

    return {
        "id": user_id, "employee_id": emp_id, "username": username, "email": email,
        "name": name, "role": role_name, "temp_password": temp_password,
        "email_sent": sent, "login_url": login_url,
    }


# ── Departments for the add-member form ───────────────────────────────────────
@router.get("/departments")
def departments(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    rows = db.execute(
        text("SELECT id, department_name FROM departments WHERE organisation_id = :org "
             "ORDER BY department_name"),
        {"org": current_user.org_id},
    ).mappings().all()
    return {"success": True, "data": [{"id": r["id"], "name": r["department_name"]} for r in rows]}


# ── Manager adds a Supervisor ─────────────────────────────────────────────────
@router.post("/add-supervisor")
def add_supervisor(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    if not _is_manager(current_user):
        raise HTTPException(status_code=403, detail="Only an HSE Manager can add a supervisor")
    d = payload.get("data", payload)
    res = _create_member(db, current_user, d.get("name"), d.get("email"),
                         "supervisor", d.get("department_id"), _employee_id(db, current_user))
    return {"success": True, "data": res}


# ── Supervisor adds a Worker ──────────────────────────────────────────────────
@router.post("/add-worker")
def add_worker(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    if not _is_supervisor(current_user):
        raise HTTPException(status_code=403, detail="Only a Supervisor can add a worker")
    d = payload.get("data", payload)
    # Worker's manager_id = the supervisor's own employee id.
    res = _create_member(db, current_user, d.get("name"), d.get("email"),
                         "operator", d.get("department_id"), _employee_id(db, current_user))
    return {"success": True, "data": res}


# ── List the team I've added ──────────────────────────────────────────────────
@router.get("/members")
def my_members(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    if _is_manager(current_user):
        rows = db.execute(
            text("SELECT u.id, u.full_name, u.email, u.username, u.is_active, u.created_at "
                 "FROM users u JOIN app_roles r ON u.app_role_id = r.id "
                 "WHERE u.organisation_id = :org AND r.name = 'supervisor' "
                 "ORDER BY u.created_at DESC"),
            {"org": current_user.org_id},
        ).mappings().all()
        label = "supervisor"
    elif _is_supervisor(current_user):
        emp = _employee_id(db, current_user)
        rows = db.execute(
            text("SELECT u.id, u.full_name, u.email, u.username, u.is_active, u.created_at "
                 "FROM users u JOIN app_roles r ON u.app_role_id = r.id "
                 "JOIN employees e ON u.employee_id = e.id "
                 "WHERE u.organisation_id = :org AND r.name = 'operator' AND e.manager_id = :mgr "
                 "ORDER BY u.created_at DESC"),
            {"org": current_user.org_id, "mgr": emp},
        ).mappings().all()
        label = "worker"
    else:
        rows, label = [], "member"

    return {
        "success": True,
        "data": {
            "role": label,
            "items": [
                {"id": r["id"], "name": r["full_name"], "email": r["email"],
                 "username": r["username"], "active": bool(r["is_active"])}
                for r in rows
            ],
        },
    }
