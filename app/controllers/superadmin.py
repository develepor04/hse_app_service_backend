from typing import List, Dict, Optional
import re
import secrets
import string
from collections import defaultdict
from pathlib import Path

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from datetime import date as dt_date

from app.config.database import get_db
from app.config.settings import get_settings
from app.core.dependencies import require_superadmin
from app.models.app_role import AppRole
from app.models.organisation_invite import OrganisationInvite
from app.models.organisation import Organisation
from app.models.notification import Notification
from app.models.subscription import Subscription
from app.models.user import User
from app.schemas.organisation_invite import (
    InviteOrganisationRequest,
    InviteOrganisationResponse,
    InviteListResponse,
)
from app.services.email_service import send_organisation_invite
from app.utils.logger import get_logger

router = APIRouter(prefix="/superadmin", tags=["SuperAdmin"], dependencies=[Depends(require_superadmin)])
settings = get_settings()
logger = get_logger(__name__)

_ALPHABET = string.ascii_letters + string.digits + "!@#$%"


def _generate_temp_password(length: int = 12) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


@router.post(
    "/invite-organisation",
    response_model=InviteOrganisationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a new organisation (SuperAdmin only)",
)
def invite_organisation(payload: InviteOrganisationRequest, db: Session = Depends(get_db)):
    """Create an organisation invite, create a User account, and send credentials to the admin email."""

    existing = (
        db.query(OrganisationInvite)
        .filter(
            OrganisationInvite.admin_email == payload.admin_email,
            OrganisationInvite.status == "pending",
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A pending invite already exists for {payload.admin_email}",
        )

    existing_user = db.query(User).filter(User.email == payload.admin_email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user account already exists for {payload.admin_email}",
        )

    admin_role = db.query(AppRole).filter(AppRole.name == "admin").first()
    if not admin_role:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Admin role not found — run app_roles seeder first",
        )

    temp_password = _generate_temp_password()
    login_url = f"{settings.frontend_url}/auth/login"

    # Derive a unique username from the email local part
    base_username = re.sub(r"[^a-z0-9_]", "_", payload.admin_email.split("@")[0].lower())
    username = base_username
    suffix = 1
    while db.query(User).filter(User.username == username).first():
        username = f"{base_username}_{suffix}"
        suffix += 1

    password_hash = bcrypt.hashpw(temp_password.encode(), bcrypt.gensalt()).decode()

    user = User(
        username=username,
        full_name=payload.admin_name,
        email=payload.admin_email,
        password_hash=password_hash,
        app_role_id=admin_role.id,
        is_active=True,
    )
    db.add(user)

    invite = OrganisationInvite(
        organisation_name=payload.organisation_name,
        admin_name=payload.admin_name,
        admin_email=payload.admin_email,
        temp_password=temp_password,
        status="pending",
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    sent = send_organisation_invite(
        admin_email=payload.admin_email,
        admin_name=payload.admin_name,
        organisation_name=payload.organisation_name,
        temp_password=temp_password,
        login_url=login_url,
    )

    if not sent:
        logger.warning(
            "Invite record created (id=%s) but email delivery failed for %s",
            invite.id,
            payload.admin_email,
        )

    logger.info(
        "Organisation invite created: id=%s org=%r email=%s email_sent=%s",
        invite.id,
        payload.organisation_name,
        payload.admin_email,
        sent,
    )
    return invite


@router.get(
    "/invites",
    response_model=InviteListResponse,
    summary="List all organisation invites",
)
def list_invites(skip: int = 0, limit: int = Query(100, le=1000), db: Session = Depends(get_db)):
    query = db.query(OrganisationInvite).order_by(OrganisationInvite.created_at.desc())
    total = query.count()
    items = query.offset(skip).limit(limit).all()
    return InviteListResponse(total=total, items=items)


@router.get(
    "/tenants",
    summary="List all tenants derived from organisation invite records",
)
def list_tenants(skip: int = 0, limit: int = Query(100, le=1000), db: Session = Depends(get_db)):
    total = db.query(OrganisationInvite).count()
    invites = (
        db.query(OrganisationInvite)
        .order_by(OrganisationInvite.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    status_map = {"pending": "pending", "accepted": "active", "expired": "suspended"}

    def to_tenant(inv: OrganisationInvite) -> dict:
        words = inv.organisation_name.upper().split()
        org_code = "".join(w[0] for w in words[:4]) + str(inv.id)
        return {
            "id": inv.id,
            "name": inv.organisation_name,
            "status": status_map.get(inv.status, "inactive"),
            "org_code": org_code,
            "plan": "Standard",
            "admin_name": inv.admin_name,
            "admin_email": inv.admin_email,
            "created_at": inv.created_at,
        }

    return {"total": total, "items": [to_tenant(i) for i in invites]}


@router.get(
    "/organisations",
    summary="List all organisations with invite metadata",
)
def list_organisations_summary(db: Session = Depends(get_db)):
    orgs = db.query(Organisation).order_by(Organisation.created_at.desc()).all()
    invites = db.query(OrganisationInvite).all()
    invite_map: Dict[str, str] = {}
    for inv in invites:
        invite_map[inv.organisation_name.lower()] = inv.status

    result = []
    for org in orgs:
        result.append(
            {
                "id": org.id,
                "organisation_name": org.organisation_name,
                "country": org.country,
                "industry_sector": org.industry_sector,
                "number_of_employees": org.number_of_employees,
                "invite_status": invite_map.get(org.organisation_name.lower(), "no_invite"),
                "created_at": org.created_at,
            }
        )
    return {"total": len(result), "items": result}


@router.get(
    "/invites/{invite_id}",
    response_model=InviteOrganisationResponse,
    summary="Get a single organisation invite",
)
def get_invite(invite_id: int, db: Session = Depends(get_db)):
    invite = db.query(OrganisationInvite).filter(OrganisationInvite.id == invite_id).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    return invite


@router.patch(
    "/invites/{invite_id}/status",
    response_model=InviteOrganisationResponse,
    summary="Update invite status",
)
def update_invite_status(
    invite_id: int,
    new_status: str,
    db: Session = Depends(get_db),
):
    if new_status not in ("pending", "accepted", "expired"):
        raise HTTPException(status_code=400, detail="Invalid status value")

    invite = db.query(OrganisationInvite).filter(OrganisationInvite.id == invite_id).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")

    invite.status = new_status
    db.commit()
    db.refresh(invite)
    return invite


@router.post(
    "/invites/{invite_id}/resend",
    response_model=InviteOrganisationResponse,
    summary="Resend invitation email with a fresh temporary password",
)
def resend_invite(invite_id: int, db: Session = Depends(get_db)):
    invite = db.query(OrganisationInvite).filter(OrganisationInvite.id == invite_id).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")

    if invite.status == "accepted":
        raise HTTPException(status_code=400, detail="Cannot resend — invite already accepted")

    # Generate a fresh password and update both invite record and user hash
    new_password = _generate_temp_password()
    invite.temp_password = new_password
    invite.status = "pending"

    user = db.query(User).filter(User.email == invite.admin_email).first()
    if user:
        user.password_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()

    db.commit()
    db.refresh(invite)

    login_url = f"{settings.frontend_url}/auth/login"
    sent = send_organisation_invite(
        admin_email=invite.admin_email,
        admin_name=invite.admin_name,
        organisation_name=invite.organisation_name,
        temp_password=new_password,
        login_url=login_url,
    )
    logger.info("Invite id=%s resent to %s email_sent=%s", invite.id, invite.admin_email, sent)
    return invite


@router.delete(
    "/invites/{invite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an organisation invite and deactivate the associated user",
)
def delete_invite(invite_id: int, db: Session = Depends(get_db)):
    invite = db.query(OrganisationInvite).filter(OrganisationInvite.id == invite_id).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")

    # Deactivate (not hard-delete) the associated user account
    user = db.query(User).filter(User.email == invite.admin_email).first()
    if user:
        user.is_active = False

    db.delete(invite)
    db.commit()


# ── Platform Users ─────────────────────────────────────────────────────────────

def _user_to_dict(u: User, role: Optional[AppRole]) -> dict:
    return {
        "id":          u.id,
        "username":    u.username,
        "email":       u.email,
        "role_name":   role.name   if role else "unknown",
        "role_label":  role.label  if role else "Unknown",
        "role_level":  role.level  if role else 0,
        "is_active":   u.is_active,
        "last_login":  u.last_login,
        "created_at":  u.created_at,
    }


@router.get("/users", summary="List all platform users")
def list_platform_users(skip: int = 0, limit: int = Query(200, le=1000), db: Session = Depends(get_db)):
    users = (
        db.query(User)
        .order_by(User.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    role_map: Dict[int, AppRole] = {r.id: r for r in db.query(AppRole).all()}
    total = db.query(User).count()
    items = [_user_to_dict(u, role_map.get(u.app_role_id)) for u in users]
    return {"total": total, "items": items}


@router.get("/roles", summary="List all app roles with user counts")
def list_roles(db: Session = Depends(get_db)):
    from sqlalchemy import func as sqlfunc
    roles = db.query(AppRole).order_by(AppRole.level.desc()).all()
    # count users per role in one query
    counts_q = (
        db.query(User.app_role_id, sqlfunc.count(User.id).label("cnt"))
        .group_by(User.app_role_id)
        .all()
    )
    counts: Dict[int, int] = {row.app_role_id: row.cnt for row in counts_q}
    return [
        {
            "id":          r.id,
            "name":        r.name,
            "label":       r.label,
            "description": r.description,
            "level":       r.level,
            "user_count":  counts.get(r.id, 0),
        }
        for r in roles
    ]


@router.patch("/roles/{role_id}", summary="Update role label and description")
def update_role(role_id: int, payload: dict, db: Session = Depends(get_db)):
    role = db.query(AppRole).filter(AppRole.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if "label" in payload and payload["label"]:
        role.label = payload["label"].strip()
    if "description" in payload:
        role.description = (payload["description"] or "").strip()
    db.commit()
    db.refresh(role)
    from sqlalchemy import func as sqlfunc
    user_count = db.query(sqlfunc.count(User.id)).filter(User.app_role_id == role.id).scalar() or 0
    return {
        "id": role.id, "name": role.name, "label": role.label,
        "description": role.description, "level": role.level, "user_count": user_count,
    }


@router.patch("/users/{user_id}/status", summary="Toggle user active status")
def toggle_user_status(user_id: int, is_active: bool, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = is_active
    db.commit()
    db.refresh(user)
    role = db.query(AppRole).filter(AppRole.id == user.app_role_id).first()
    return _user_to_dict(user, role)


@router.patch("/users/{user_id}/role", summary="Change user role")
def change_user_role(user_id: int, role_name: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    role = db.query(AppRole).filter(AppRole.name == role_name).first()
    if not role:
        raise HTTPException(status_code=400, detail=f"Role '{role_name}' not found")
    user.app_role_id = role.id
    db.commit()
    db.refresh(user)
    return _user_to_dict(user, role)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a user")
def delete_platform_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()


@router.post("/users", status_code=status.HTTP_201_CREATED, summary="Create a platform user")
def create_platform_user(payload: dict, db: Session = Depends(get_db)):
    email = (payload.get("email") or "").strip().lower()
    username = (payload.get("username") or "").strip()
    role_name = (payload.get("role_name") or "viewer").strip()
    plain_password = (payload.get("password") or "").strip()

    if not email or not username or not plain_password:
        raise HTTPException(status_code=400, detail="email, username and password are required")

    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail=f"Email {email} already exists")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=409, detail=f"Username {username} already exists")

    role = db.query(AppRole).filter(AppRole.name == role_name).first()
    if not role:
        raise HTTPException(status_code=400, detail=f"Role '{role_name}' not found")

    password_hash = bcrypt.hashpw(plain_password.encode(), bcrypt.gensalt()).decode()
    user = User(username=username, email=email, password_hash=password_hash,
                app_role_id=role.id, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_to_dict(user, role)


# ── Subscriptions ──────────────────────────────────────────────────────────────

_PLAN_DEFAULTS = {
    "trial":      {"amount": 0.00,    "seats": 5,    "label": "Free Trial"},
    "standard":   {"amount": 49.00,   "seats": 50,   "label": "Standard"},
    "premium":    {"amount": 149.00,  "seats": 200,  "label": "Premium"},
    "enterprise": {"amount": 0.00,    "seats": None, "label": "Enterprise"},
}


def _sub_to_dict(sub: Subscription, invite: Optional[OrganisationInvite]) -> dict:
    return {
        "id":            sub.id,
        "invite_id":     sub.invite_id,
        "org_name":      invite.organisation_name if invite else "—",
        "admin_email":   invite.admin_email       if invite else "—",
        "plan_name":     sub.plan_name,
        "plan_label":    _PLAN_DEFAULTS.get(sub.plan_name, {}).get("label", sub.plan_name.title()),
        "status":        sub.status,
        "billing_cycle": sub.billing_cycle,
        "amount":        float(sub.amount),
        "seats":         sub.seats,
        "start_date":    sub.start_date.isoformat()  if sub.start_date  else None,
        "end_date":      sub.end_date.isoformat()    if sub.end_date    else None,
        "notes":         sub.notes,
        "created_at":    sub.created_at,
        "updated_at":    sub.updated_at,
    }


@router.get("/subscriptions", summary="List all subscriptions")
def list_subscriptions(skip: int = 0, limit: int = Query(200, le=1000), db: Session = Depends(get_db)):
    subs = (
        db.query(Subscription)
        .order_by(Subscription.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    invite_map: Dict[int, OrganisationInvite] = {
        i.id: i for i in db.query(OrganisationInvite).all()
    }
    total = db.query(Subscription).count()
    return {
        "total": total,
        "items": [_sub_to_dict(s, invite_map.get(s.invite_id)) for s in subs],
        "mrr":   sum(float(s.amount) for s in subs if s.status == "active" and s.billing_cycle == "monthly"),
        "arr":   sum(float(s.amount) * 12 for s in subs if s.status == "active" and s.billing_cycle == "monthly")
              +  sum(float(s.amount) for s in subs if s.status == "active" and s.billing_cycle == "annual"),
    }


@router.post("/subscriptions", status_code=status.HTTP_201_CREATED, summary="Create a subscription")
def create_subscription(payload: dict, db: Session = Depends(get_db)):
    invite_id  = payload.get("invite_id")
    plan_name  = (payload.get("plan_name") or "standard").strip().lower()
    billing    = (payload.get("billing_cycle") or "monthly").strip().lower()
    amount     = payload.get("amount")
    seats      = payload.get("seats")
    start_str  = payload.get("start_date")
    end_str    = payload.get("end_date")
    notes      = (payload.get("notes") or "").strip() or None

    if plan_name not in _PLAN_DEFAULTS:
        raise HTTPException(status_code=400, detail=f"Unknown plan '{plan_name}'")

    defaults = _PLAN_DEFAULTS[plan_name]
    if amount is None:
        amount = defaults["amount"]
    if seats is None:
        seats = defaults["seats"]

    invite = None
    if invite_id:
        invite = db.query(OrganisationInvite).filter(OrganisationInvite.id == invite_id).first()
        if not invite:
            raise HTTPException(status_code=404, detail="Organisation invite not found")
        # prevent duplicate
        existing = db.query(Subscription).filter(
            Subscription.invite_id == invite_id,
            Subscription.status.in_(["trial", "active"]),
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="An active subscription already exists for this organisation")

    start = dt_date.fromisoformat(start_str) if start_str else dt_date.today()
    end   = dt_date.fromisoformat(end_str)   if end_str   else None

    sub = Subscription(
        invite_id=invite_id,
        plan_name=plan_name,
        status="trial" if plan_name == "trial" else "active",
        billing_cycle=billing,
        amount=amount,
        seats=seats,
        start_date=start,
        end_date=end,
        notes=notes,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return _sub_to_dict(sub, invite)


@router.patch("/subscriptions/{sub_id}", summary="Update a subscription")
def update_subscription(sub_id: int, payload: dict, db: Session = Depends(get_db)):
    sub = db.query(Subscription).filter(Subscription.id == sub_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    if "plan_name" in payload and payload["plan_name"]:
        pname = payload["plan_name"].strip().lower()
        if pname not in _PLAN_DEFAULTS:
            raise HTTPException(status_code=400, detail=f"Unknown plan '{pname}'")
        sub.plan_name = pname

    if "status" in payload and payload["status"]:
        sub.status = payload["status"]
    if "billing_cycle" in payload and payload["billing_cycle"]:
        sub.billing_cycle = payload["billing_cycle"]
    if "amount" in payload and payload["amount"] is not None:
        sub.amount = payload["amount"]
    if "seats" in payload:
        sub.seats = payload["seats"]
    if "start_date" in payload:
        sub.start_date = dt_date.fromisoformat(payload["start_date"]) if payload["start_date"] else None
    if "end_date" in payload:
        sub.end_date = dt_date.fromisoformat(payload["end_date"]) if payload["end_date"] else None
    if "notes" in payload:
        sub.notes = (payload["notes"] or "").strip() or None

    db.commit()
    db.refresh(sub)
    invite = db.query(OrganisationInvite).filter(OrganisationInvite.id == sub.invite_id).first() if sub.invite_id else None
    return _sub_to_dict(sub, invite)


@router.delete("/subscriptions/{sub_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a subscription")
def delete_subscription(sub_id: int, db: Session = Depends(get_db)):
    sub = db.query(Subscription).filter(Subscription.id == sub_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    db.delete(sub)
    db.commit()


# ── Platform Analytics ─────────────────────────────────────────────────────────

@router.get("/analytics", summary="Platform-wide analytics snapshot")
def platform_analytics(db: Session = Depends(get_db)):
    from sqlalchemy import func as sqlfunc, text
    from app.models.subscription import Subscription as SubModel

    # ── Core counts ──────────────────────────────────────────────────────────
    total_users    = db.query(sqlfunc.count(User.id)).scalar() or 0
    active_users   = db.query(sqlfunc.count(User.id)).filter(User.is_active == True).scalar() or 0
    total_tenants  = db.query(sqlfunc.count(OrganisationInvite.id)).scalar() or 0
    active_tenants = db.query(sqlfunc.count(OrganisationInvite.id)).filter(OrganisationInvite.status == "accepted").scalar() or 0
    pending_tenants = db.query(sqlfunc.count(OrganisationInvite.id)).filter(OrganisationInvite.status == "pending").scalar() or 0
    total_subs     = db.query(sqlfunc.count(SubModel.id)).scalar() or 0
    active_subs    = db.query(sqlfunc.count(SubModel.id)).filter(SubModel.status == "active").scalar() or 0

    mrr_row = db.query(sqlfunc.sum(SubModel.amount)).filter(
        SubModel.status == "active", SubModel.billing_cycle == "monthly"
    ).scalar()
    annual_row = db.query(sqlfunc.sum(SubModel.amount)).filter(
        SubModel.status == "active", SubModel.billing_cycle == "annual"
    ).scalar()
    mrr = float(mrr_row or 0)
    arr = mrr * 12 + float(annual_row or 0)

    # ── Role distribution ─────────────────────────────────────────────────────
    role_counts_q = (
        db.query(AppRole.label, sqlfunc.count(User.id).label("cnt"))
        .outerjoin(User, User.app_role_id == AppRole.id)
        .group_by(AppRole.id, AppRole.label)
        .all()
    )
    role_distribution = [{"role": r.label, "count": r.cnt} for r in role_counts_q]

    # ── Subscription plan distribution ────────────────────────────────────────
    plan_q = (
        db.query(SubModel.plan_name, sqlfunc.count(SubModel.id).label("cnt"),
                 sqlfunc.sum(SubModel.amount).label("revenue"))
        .filter(SubModel.status.in_(["active", "trial"]))
        .group_by(SubModel.plan_name)
        .all()
    )
    plan_distribution = [
        {"plan": p.plan_name, "count": p.cnt, "revenue": float(p.revenue or 0)}
        for p in plan_q
    ]

    # ── Tenant status distribution ────────────────────────────────────────────
    tenant_status_q = (
        db.query(OrganisationInvite.status, sqlfunc.count(OrganisationInvite.id).label("cnt"))
        .group_by(OrganisationInvite.status)
        .all()
    )
    tenant_status = [{"status": t.status, "count": t.cnt} for t in tenant_status_q]

    # ── Monthly growth: tenants invited (last 12 months) ─────────────────────
    monthly_q = db.execute(text("""
        SELECT DATE_FORMAT(created_at,'%Y-%m') as month,
               COUNT(*) as new_tenants
        FROM organisation_invite
        WHERE created_at >= DATE_SUB(NOW(), INTERVAL 12 MONTH)
        GROUP BY month ORDER BY month ASC
    """)).fetchall()
    tenant_growth = [{"month": r[0], "tenants": r[1]} for r in monthly_q]

    # ── Monthly user signups (last 12 months) ─────────────────────────────────
    user_growth_q = db.execute(text("""
        SELECT DATE_FORMAT(created_at,'%Y-%m') as month, COUNT(*) as new_users
        FROM users
        WHERE created_at >= DATE_SUB(NOW(), INTERVAL 12 MONTH)
        GROUP BY month ORDER BY month ASC
    """)).fetchall()
    user_growth = [{"month": r[0], "users": r[1]} for r in user_growth_q]

    # ── Recent tenants ────────────────────────────────────────────────────────
    recent_invites = (
        db.query(OrganisationInvite)
        .order_by(OrganisationInvite.created_at.desc())
        .limit(5)
        .all()
    )
    recent_tenants = [
        {
            "id": i.id,
            "name": i.organisation_name,
            "status": i.status,
            "created_at": i.created_at,
        }
        for i in recent_invites
    ]

    return {
        "overview": {
            "total_users":     total_users,
            "active_users":    active_users,
            "total_tenants":   total_tenants,
            "active_tenants":  active_tenants,
            "pending_tenants": pending_tenants,
            "total_subs":      total_subs,
            "active_subs":     active_subs,
            "mrr":             mrr,
            "arr":             arr,
        },
        "role_distribution":   role_distribution,
        "plan_distribution":   plan_distribution,
        "tenant_status":       tenant_status,
        "tenant_growth":       tenant_growth,
        "user_growth":         user_growth,
        "recent_tenants":      recent_tenants,
    }


# ── System Settings ────────────────────────────────────────────────────────────

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

_EDITABLE_KEYS = {
    "app_name", "debug", "frontend_base_url", "log_level",
    "access_token_expire_minutes",
    "email_backend",
    "sendgrid_api_key", "sendgrid_from_email", "sendgrid_from_name",
    "smtp_host", "smtp_port", "smtp_user", "smtp_password",
    "smtp_from_email", "smtp_from_name",
    "smtp_use_tls", "smtp_use_ssl",
    "allowed_origins",
}


def _read_env_file() -> dict:
    result: Dict[str, str] = {}
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key, _, val = stripped.partition("=")
                result[key.strip()] = val.strip()
    return result


def _write_env_file(env_dict: dict) -> None:
    lines = [f"{k}={v}" for k, v in env_dict.items()]
    _ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


@router.get("/settings", summary="Get platform system settings")
def get_platform_settings():
    import re as _re
    s = get_settings()
    masked_sg = ""
    if s.sendgrid_api_key:
        masked_sg = ("*" * 8 + s.sendgrid_api_key[-4:]) if len(s.sendgrid_api_key) > 4 else "****"

    masked_smtp_pw = ""
    if s.smtp_password:
        masked_smtp_pw = "*" * min(len(s.smtp_password), 10)

    # Derive effective backend for display
    mode = (s.email_backend or "auto").strip().lower()
    if mode == "sendgrid":
        effective_backend = "sendgrid"
    elif mode == "smtp":
        effective_backend = "smtp"
    elif s.sendgrid_api_key:
        effective_backend = "sendgrid"
    elif s.smtp_host:
        effective_backend = "smtp"
    else:
        effective_backend = "none"

    # Parse DATABASE_URL to extract display components
    db_host, db_port_n, db_name_str, db_user_str = "localhost", 3306, "hse_db", "root"
    m = _re.match(r"[^:]+://([^:@]*)(?::[^@]*)?@([^:/?]+)(?::(\d+))?/([^?]*)", s.database_url)
    if m:
        db_user_str  = m.group(1) or db_user_str
        db_host      = m.group(2) or db_host
        db_port_n    = int(m.group(3)) if m.group(3) else db_port_n
        db_name_str  = m.group(4) or db_name_str

    return {
        "platform": {
            "app_name":    s.app_name,
            "app_env":     s.app_env,
            "app_version": s.app_version,
            "app_debug":   s.debug,
            "frontend_url": s.frontend_base_url,
            "log_level":   s.log_level,
        },
        "database": {
            "db_host":        db_host,
            "db_port":        db_port_n,
            "db_name":        db_name_str,
            "db_user":        db_user_str,
            "db_pool_size":   s.db_pool_size,
            "db_max_overflow": s.db_max_overflow,
            "db_pool_timeout": s.db_pool_timeout,
        },
        "auth": {
            "jwt_algorithm":                   s.jwt_algorithm,
            "jwt_access_token_expire_minutes": s.access_token_expire_minutes,
            "jwt_secret_configured":           s.jwt_secret != "hse-local-dev-secret-change-in-production",
        },
        "email": {
            "email_backend":           s.email_backend,
            "effective_backend":       effective_backend,
            "sendgrid_from_email":     s.sendgrid_from_email,
            "sendgrid_from_name":      s.sendgrid_from_name,
            "smtp_from_email":         s.smtp_from_email,
            "smtp_from_name":          s.smtp_from_name,
            "sendgrid_configured":     bool(s.sendgrid_api_key),
            "sendgrid_api_key_masked": masked_sg,
            "smtp_host":               s.smtp_host,
            "smtp_port":               s.smtp_port,
            "smtp_user":               s.smtp_user,
            "smtp_password_set":       bool(s.smtp_password),
            "smtp_password_masked":    masked_smtp_pw,
            "smtp_use_tls":            s.smtp_use_tls,
            "smtp_use_ssl":            s.smtp_use_ssl,
        },
        "security": {
            "allowed_origins":       s.cors_origins,
            "secret_key_configured": s.jwt_secret != "hse-local-dev-secret-change-in-production",
        },
    }


@router.patch("/settings", summary="Update editable platform settings (restart required)")
def update_platform_settings(payload: dict):
    env_dict = _read_env_file()
    updated: List[str] = []
    rejected: List[str] = []

    for key, value in payload.items():
        if key not in _EDITABLE_KEYS:
            rejected.append(key)
            continue
        env_key = key.upper()
        if isinstance(value, bool):
            env_Dict[env_key] = str(value).lower()
        elif isinstance(value, list):
            env_Dict[env_key] = ",".join(str(v) for v in value)
        else:
            env_Dict[env_key] = str(value)
        updated.append(key)

    _write_env_file(env_dict)
    return {"updated": updated, "rejected": rejected, "restart_required": True}


# ── Notifications ──────────────────────────────────────────────────────────────

def _notif_to_dict(n: Notification, invite: Optional[OrganisationInvite]) -> dict:
    return {
        "id":               n.id,
        "title":            n.title,
        "message":          n.message,
        "type":             n.type,
        "target_type":      n.target_type,
        "target_invite_id": n.target_invite_id,
        "target_org_name":  invite.organisation_name if invite else None,
        "status":           n.status,
        "email_sent_count": n.email_sent_count,
        "sent_at":          n.sent_at,
        "created_at":       n.created_at,
        "updated_at":       n.updated_at,
    }


@router.get("/notifications", summary="List all platform notifications")
def list_notifications(skip: int = 0, limit: int = Query(100, le=1000), db: Session = Depends(get_db)):
    from sqlalchemy import func as sqlfunc
    total = db.query(sqlfunc.count(Notification.id)).scalar() or 0
    items = (
        db.query(Notification)
        .order_by(Notification.created_at.desc())
        .offset(skip).limit(limit).all()
    )
    invite_map: Dict[int, OrganisationInvite] = {i.id: i for i in db.query(OrganisationInvite).all()}
    stats = {
        "total":  total,
        "sent":   db.query(sqlfunc.count(Notification.id)).filter(Notification.status == "sent").scalar() or 0,
        "draft":  db.query(sqlfunc.count(Notification.id)).filter(Notification.status == "draft").scalar() or 0,
        "failed": db.query(sqlfunc.count(Notification.id)).filter(Notification.status == "failed").scalar() or 0,
    }
    return {
        "total": total,
        "stats": stats,
        "items": [_notif_to_dict(n, invite_map.get(n.target_invite_id)) for n in items],
    }


@router.post("/notifications", status_code=status.HTTP_201_CREATED, summary="Create a notification (draft)")
def create_notification(payload: dict, db: Session = Depends(get_db)):
    title       = (payload.get("title") or "").strip()
    message     = (payload.get("message") or "").strip()
    notif_type  = (payload.get("type") or "info").strip()
    target_type = (payload.get("target_type") or "all").strip()
    invite_id   = payload.get("target_invite_id")

    if not title or not message:
        raise HTTPException(status_code=400, detail="title and message are required")

    invite = None
    if target_type == "specific" and invite_id:
        invite = db.query(OrganisationInvite).filter(OrganisationInvite.id == invite_id).first()
        if not invite:
            raise HTTPException(status_code=404, detail="Target organisation not found")

    n = Notification(
        title=title, message=message, type=notif_type,
        target_type=target_type, target_invite_id=invite_id if target_type == "specific" else None,
        status="draft",
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    return _notif_to_dict(n, invite)


@router.post("/notifications/{notif_id}/send", summary="Send a notification (email blast)")
def send_notification(notif_id: int, db: Session = Depends(get_db)):
    from datetime import datetime as dt_now
    from app.services.email_service import send_email

    n = db.query(Notification).filter(Notification.id == notif_id).first()
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    if n.status == "sent":
        raise HTTPException(status_code=400, detail="Notification already sent")

    # Determine recipients
    if n.target_type == "all":
        invites = db.query(OrganisationInvite).all()
    else:
        inv = db.query(OrganisationInvite).filter(OrganisationInvite.id == n.target_invite_id).first()
        invites = [inv] if inv else []

    sent_count = 0
    for inv in invites:
        html = _build_notification_html(
            admin_name=inv.admin_name,
            org_name=inv.organisation_name,
            notif_type=n.type,
            title=n.title,
            message=n.message,
        )
        ok = send_email(
            to_email=inv.admin_email,
            subject=f"[EHSERA Intelligence] {n.title}",
            html_content=html,
            to_name=inv.admin_name,
        )
        if ok:
            sent_count += 1

    n.status = "sent" if sent_count > 0 or not invites else "failed"
    n.email_sent_count = sent_count
    n.sent_at = dt_now.utcnow()
    db.commit()
    db.refresh(n)

    invite = db.query(OrganisationInvite).filter(OrganisationInvite.id == n.target_invite_id).first() if n.target_invite_id else None
    return _notif_to_dict(n, invite)


@router.delete("/notifications/{notif_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a notification")
def delete_notification(notif_id: int, db: Session = Depends(get_db)):
    n = db.query(Notification).filter(Notification.id == notif_id).first()
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    db.delete(n)
    db.commit()


_NOTIF_TYPE_COLORS = {
    "info":         "#1D4ED8",
    "success":      "#059669",
    "warning":      "#D97706",
    "maintenance":  "#7C3AED",
    "announcement": "#0891B2",
}
_NOTIF_TYPE_LABELS = {
    "info":         "Info",
    "success":      "Success",
    "warning":      "Warning",
    "maintenance":  "Maintenance",
    "announcement": "Announcement",
}


def _build_notification_html(admin_name: str, org_name: str, notif_type: str, title: str, message: str) -> str:
    color = _NOTIF_TYPE_COLORS.get(notif_type, "#1D4ED8")
    label = _NOTIF_TYPE_LABELS.get(notif_type, "Notification")
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/></head>
<body style="margin:0;padding:0;background:#F3F7FF;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F3F7FF;padding:40px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:12px;border:1px solid #D6E4FF;
                    box-shadow:0 4px 20px rgba(0,0,0,0.08);overflow:hidden;">
        <tr>
          <td style="background:linear-gradient(135deg,{color},{color}cc);padding:28px 40px;">
            <div style="display:inline-block;background:rgba(255,255,255,0.2);
                        border-radius:20px;padding:4px 14px;margin-bottom:10px;">
              <span style="color:#fff;font-size:12px;font-weight:600;text-transform:uppercase;
                           letter-spacing:1px;">{label}</span>
            </div>
            <h1 style="margin:0;color:#fff;font-size:22px;font-weight:700;">{title}</h1>
          </td>
        </tr>
        <tr>
          <td style="padding:36px 40px;">
            <p style="margin:0 0 12px;color:#374151;font-size:15px;">Hi {admin_name},</p>
            <p style="margin:0 0 20px;color:#6B7280;font-size:13px;">
              This is a platform notification for <strong style="color:{color};">{org_name}</strong>.
            </p>
            <div style="background:#F8FAFF;border-left:4px solid {color};border-radius:4px;
                        padding:16px 20px;margin-bottom:24px;">
              <p style="margin:0;color:#1F2937;font-size:14px;line-height:1.7;">{message}</p>
            </div>
            <hr style="border:none;border-top:1px solid #E5E7EB;margin:0 0 20px;"/>
            <p style="margin:0;color:#9CA3AF;font-size:12px;">
              Sent by EHSERA Intelligence Super Admin &bull;
              <a href="mailto:support@hse-intelligence.com" style="color:{color};text-decoration:none;">
                support@hse-intelligence.com</a>
            </p>
          </td>
        </tr>
        <tr>
          <td style="background:#F9FAFB;border-top:1px solid #E5E7EB;padding:16px 40px;text-align:center;">
            <p style="margin:0;color:#9CA3AF;font-size:11px;">&copy; 2026 EHSERA Intelligence. All rights reserved.</p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
