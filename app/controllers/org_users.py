"""Org Admin — invite and manage users within their organisation."""
import re
import secrets
import string

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.config.settings import get_settings
from app.core.dependencies import get_current_user, CurrentUser
from app.models.app_role import AppRole
from app.models.employee import Employee
from app.models.organisation import Organisation
from app.models.organisation_invite import OrganisationInvite
from app.models.user import User
from app.services.email_service import send_email, _build_invite_html
from app.services.audit_log import record_audit, resolve_employee_id
from app.utils.logger import get_logger

router = APIRouter(prefix="/org", tags=["Org Users"])
settings = get_settings()
logger = get_logger(__name__)

_ALPHABET = string.ascii_letters + string.digits + "!@#$%"

# Roles that org admin can assign (cannot create another admin or superadmin)
INVITABLE_ROLES = {"safety_manager", "supervisor", "operator", "auditor", "viewer"}

# Who can invite whom — mirrors the org hierarchy story: Admin invites the HSE
# Manager (safety_manager); the HSE Manager then invites Supervisors (and can
# also add operators/viewers directly). Supervisors don't invite via email —
# they add Workers through the mobile app's /team/add-worker flow instead.
INVITE_PERMISSIONS = {
    "admin": {"safety_manager", "supervisor", "operator", "auditor", "viewer"},
    "safety_manager": {"supervisor", "operator", "auditor", "viewer"},
}


def _gen_password(length: int = 12) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def _resolve_org_id(current_user: CurrentUser, db: Session) -> int:
    """Return the org_id for the current org admin.
    If not yet set on their JWT (e.g. right after org wizard), look it up
    from the organisation_invite → organisation table.
    """
    if current_user.org_id is not None and current_user.org_id > 0:
        return current_user.org_id

    # Find their accepted invite
    invite = (
        db.query(OrganisationInvite)
        .filter(OrganisationInvite.admin_email == current_user.email)
        .order_by(OrganisationInvite.id.desc())
        .first()
    )
    if not invite:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organisation setup not found. Please complete org setup wizard first.",
        )

    # Find org by name (created during Excel import)
    org = (
        db.query(Organisation)
        .filter(Organisation.organisation_name == invite.organisation_name)
        .first()
    )
    if not org:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organisation not created yet. Please complete org setup wizard first.",
        )

    # Also update the admin's own record so future JWTs carry the org_id
    admin_user = db.query(User).filter(User.email == current_user.email).first()
    if admin_user and admin_user.organisation_id is None:
        admin_user.organisation_id = org.id
        db.commit()
        logger.info("Auto-assigned org_id=%s to admin %s", org.id, current_user.email)

    return org.id


@router.post(
    "/invite-user",
    status_code=status.HTTP_201_CREATED,
    summary="Org Admin: invite a user to the organisation",
)
def invite_user(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    name = (payload.get("name") or "").strip()
    email = (payload.get("email") or "").strip().lower()
    role_name = (payload.get("role") or "operator").strip().lower()
    # Optional, but the whole point of collecting it at invite time: an employee
    # with no department cannot be routed to a supervisor, and incidents they
    # report fall back to "any supervisor in the org". Validated against the
    # inviter's own organisation below so one tenant cannot file a person into
    # another tenant's department.
    department_id = payload.get("department_id")

    if not name or not email:
        raise HTTPException(status_code=400, detail="name and email are required")

    if role_name not in INVITABLE_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role. Allowed: {sorted(INVITABLE_ROLES)}",
        )

    inviter_role = (current_user.role or "").strip().lower()
    allowed_targets = INVITE_PERMISSIONS.get(inviter_role)
    if not allowed_targets:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an Admin or HSE Manager can invite users",
        )
    if role_name not in allowed_targets:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"As {inviter_role.replace('_', ' ').title()} you can only invite: {sorted(allowed_targets)}",
        )

    if db.query(User).filter(User.email == email).first():
        raise HTTPException(
            status_code=409,
            detail=f"A user with email {email} already exists",
        )

    app_role = db.query(AppRole).filter(AppRole.name == role_name).first()
    if not app_role:
        raise HTTPException(status_code=400, detail=f"Role '{role_name}' not found in app_roles")

    org_id = _resolve_org_id(current_user, db)

    base_username = re.sub(r"[^a-z0-9_]", "_", email.split("@")[0].lower())
    username = base_username
    suffix = 1
    while db.query(User).filter(User.username == username).first():
        username = f"{base_username}_{suffix}"
        suffix += 1

    temp_password = _gen_password()
    password_hash = bcrypt.hashpw(temp_password.encode(), bcrypt.gensalt()).decode()

    # Create the linked HR/employee record too. Without it an invited user has no
    # employees row, so they never show up in employee-based views — supervisors
    # can't see or assign tasks to them, and /employees/me has nothing to return.
    # This mirrors what /team/add-worker already does.
    if department_id is not None:
        try:
            department_id = int(department_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="department_id must be a number")
        in_org = db.execute(
            text("SELECT id FROM departments WHERE id = :id AND organisation_id = :org"),
            {"id": department_id, "org": org_id},
        ).scalar()
        if not in_org:
            raise HTTPException(
                status_code=400,
                detail="That department does not belong to your organisation",
            )

    employee = Employee(
        full_name=name,
        organisation_id=org_id,
        employment_type="Full-time",
        active_status="Active",
        department_id=department_id,
    )
    db.add(employee)
    db.flush()  # populate employee.id for the FK below

    user = User(
        username=username,
        full_name=name,
        email=email,
        password_hash=password_hash,
        app_role_id=app_role.id,
        organisation_id=org_id,
        employee_id=employee.id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    login_url = f"{settings.frontend_url}/auth/login"

    # Get org name for the email
    org = db.query(Organisation).filter(Organisation.id == org_id).first()
    org_name = org.organisation_name if org else "your organisation"

    html = _build_invite_html(
        admin_name=name,
        organisation_name=org_name,
        email=email,
        temp_password=temp_password,
        login_url=login_url,
    )
    sent = send_email(
        to_email=email,
        subject=f"You've been invited to {org_name} — EHSERA Intelligence",
        html_content=html,
        to_name=name,
    )

    logger.info(
        "User invite created: id=%s email=%s role=%s org_id=%s email_sent=%s",
        user.id, email, role_name, org_id, sent,
    )

    return {
        "id": user.id,
        "username": username,
        "email": email,
        "name": name,
        "role": role_name,
        "role_label": app_role.label,
        "organisation_id": org_id,
        "temp_password": temp_password,
        "email_sent": sent,
        "login_url": login_url,
    }


@router.get("/users", summary="Org Admin: list all users in the organisation")
def list_org_users(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    org_id = _resolve_org_id(current_user, db)
    role_map = {r.id: r for r in db.query(AppRole).all()}

    users = (
        db.query(User)
        .filter(User.organisation_id == org_id)
        .order_by(User.created_at.desc())
        .all()
    )

    return {
        "total": len(users),
        "items": [
            {
                "id": u.id,
                "username": u.username,
                "email": u.email,
                "role": role_map[u.app_role_id].name if u.app_role_id in role_map else "unknown",
                "role_label": role_map[u.app_role_id].label if u.app_role_id in role_map else "Unknown",
                "is_active": u.is_active,
                "created_at": u.created_at,
            }
            for u in users
        ],
    }


@router.patch("/users/{user_id}/toggle", summary="Org Admin: enable or disable a user")
def toggle_user(
    user_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    org_id = _resolve_org_id(current_user, db)
    user = db.query(User).filter(User.id == user_id, User.organisation_id == org_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found in your organisation")

    role = db.query(AppRole).filter(AppRole.id == user.app_role_id).first()
    if role and role.name in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Cannot modify admin accounts")

    previous_active = user.is_active
    user.is_active = bool(payload.get("is_active", True))
    record_audit(
        db, org_id, resolve_employee_id(db, current_user.user_id),
        action="activate" if user.is_active else "deactivate", module="User Account",
        record_id=user.id, previous_value=str(previous_active), new_value=str(user.is_active),
    )
    db.commit()
    return {"id": user.id, "email": user.email, "is_active": user.is_active}


@router.patch("/users/{user_id}/role", summary="Org Admin: change a user's role")
def change_user_role(
    user_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    org_id = _resolve_org_id(current_user, db)
    user = db.query(User).filter(User.id == user_id, User.organisation_id == org_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found in your organisation")

    role_name = (payload.get("role") or "").strip().lower()
    if role_name not in INVITABLE_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Allowed: {sorted(INVITABLE_ROLES)}")

    app_role = db.query(AppRole).filter(AppRole.name == role_name).first()
    if not app_role:
        raise HTTPException(status_code=400, detail=f"Role '{role_name}' not found")

    previous_role = db.query(AppRole).filter(AppRole.id == user.app_role_id).first()
    user.app_role_id = app_role.id
    record_audit(
        db, org_id, resolve_employee_id(db, current_user.user_id),
        action="update", module="User Role", record_id=user.id,
        previous_value=previous_role.label if previous_role else None, new_value=app_role.label,
    )
    db.commit()
    return {"id": user.id, "email": user.email, "role": role_name, "role_label": app_role.label}


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Org Admin: remove a user")
def remove_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    org_id = _resolve_org_id(current_user, db)
    user = db.query(User).filter(User.id == user_id, User.organisation_id == org_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found in your organisation")

    role = db.query(AppRole).filter(AppRole.id == user.app_role_id).first()
    if role and role.name in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Cannot delete admin accounts")

    record_audit(
        db, org_id, resolve_employee_id(db, current_user.user_id),
        action="delete", module="User Account", record_id=user.id, previous_value=user.email,
    )
    db.delete(user)
    db.commit()
