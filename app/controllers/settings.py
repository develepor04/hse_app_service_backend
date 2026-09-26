import hashlib
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.models.api_key import ApiKey
from app.models.webhook import Webhook
from app.models.organisation import Organisation
from app.models.audit_log import AuditLog
from app.services.audit_log import record_audit, resolve_employee_id
from app.services.contractor_risk import DEFAULT_CONTRACTOR_WEIGHTS
from app.services.rating_labels import DEFAULT_RATING_LABELS
from app.utils.tenant import org_scoped_join

router = APIRouter(prefix="/org-admin/settings", tags=["Settings"])


def _org_filter(query, model, org_id):
    if org_id is not None:
        return query.filter(model.organisation_id == org_id)
    return query


# ── API Keys ────────────────────────────────────────────────────────────────────
# Keys are shown in full only once, at generation time — only a hash and a
# display prefix are ever stored, matching standard API-key handling practice.

def _api_key_to_dict(row: ApiKey) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "prefix": row.key_prefix,
        "scopes": row.scopes,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
    }


@router.get("/api-keys")
def list_api_keys(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)) -> dict:
    rows = (
        _org_filter(db.query(ApiKey), ApiKey, current_user.org_id)
        .filter(ApiKey.is_active == True)
        .order_by(ApiKey.id.desc())
        .all()
    )
    return {"data": [_api_key_to_dict(r) for r in rows]}


@router.post("/api-keys")
def create_api_key(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Key name is required")
    scopes = payload.get("scopes") or "Read"

    raw_key = "hse_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    prefix = raw_key[:12] + "..."

    row = ApiKey(
        organisation_id=current_user.org_id,
        name=name,
        key_prefix=prefix,
        key_hash=key_hash,
        scopes=scopes,
        created_by=current_user.email,
    )
    db.add(row)
    record_audit(
        db, current_user.org_id, resolve_employee_id(db, current_user.user_id),
        action="create", module="API Key", new_value=name,
    )
    db.commit()
    db.refresh(row)

    result = _api_key_to_dict(row)
    result["raw_key"] = raw_key  # only ever returned once, on creation
    return {"data": result}


@router.delete("/api-keys/{key_id}")
def revoke_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    row = (
        _org_filter(db.query(ApiKey), ApiKey, current_user.org_id)
        .filter(ApiKey.id == key_id)
        .first()
    )
    if row:
        row.is_active = False
        record_audit(
            db, current_user.org_id, resolve_employee_id(db, current_user.user_id),
            action="revoke", module="API Key", record_id=row.id, previous_value=row.name,
        )
        db.commit()
    return {"revoked": True}


# ── Webhooks ──────────────────────────────────────────────────────────────────

def _webhook_to_dict(row: Webhook) -> dict:
    return {
        "id": row.id,
        "url": row.url,
        "event_types": row.event_types,
        "is_active": row.is_active,
        "last_triggered_at": row.last_triggered_at.isoformat() if row.last_triggered_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


@router.get("/webhooks")
def list_webhooks(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)) -> dict:
    rows = (
        _org_filter(db.query(Webhook), Webhook, current_user.org_id)
        .filter(Webhook.is_active == True)
        .order_by(Webhook.id.desc())
        .all()
    )
    return {"data": [_webhook_to_dict(r) for r in rows]}


@router.post("/webhooks")
def create_webhook(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    url = (payload.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Webhook URL is required")
    event_types = payload.get("event_types") or ""

    row = Webhook(
        organisation_id=current_user.org_id,
        url=url,
        event_types=event_types,
        secret=secrets.token_urlsafe(24),
    )
    db.add(row)
    record_audit(
        db, current_user.org_id, resolve_employee_id(db, current_user.user_id),
        action="create", module="Webhook", new_value=url,
    )
    db.commit()
    db.refresh(row)
    return {"data": _webhook_to_dict(row)}


@router.delete("/webhooks/{webhook_id}")
def delete_webhook(
    webhook_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    row = (
        _org_filter(db.query(Webhook), Webhook, current_user.org_id)
        .filter(Webhook.id == webhook_id)
        .first()
    )
    if row:
        record_audit(
            db, current_user.org_id, resolve_employee_id(db, current_user.user_id),
            action="delete", module="Webhook", record_id=row.id, previous_value=row.url,
        )
        db.delete(row)
        db.commit()
    return {"deleted": True}


# ── Branding ──────────────────────────────────────────────────────────────────

_DEFAULT_BRANDING = {"logo_url": None, "primary_color": "#1B5E20"}


@router.get("/branding")
def get_branding(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)) -> dict:
    if not current_user.org_id:
        return {"data": _DEFAULT_BRANDING}
    org = db.query(Organisation).filter(Organisation.id == current_user.org_id).first()
    if not org or not org.branding:
        return {"data": _DEFAULT_BRANDING}
    return {"data": {**_DEFAULT_BRANDING, **org.branding}}


@router.put("/branding")
def save_branding(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    if not current_user.org_id:
        raise HTTPException(status_code=400, detail="No organisation on this account")
    org = db.query(Organisation).filter(Organisation.id == current_user.org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    previous = dict(org.branding) if org.branding else dict(_DEFAULT_BRANDING)
    primary_color = payload.get("primary_color") or _DEFAULT_BRANDING["primary_color"]
    logo_url = payload.get("logo_url")
    org.branding = {"primary_color": primary_color, "logo_url": logo_url}
    record_audit(
        db, current_user.org_id, resolve_employee_id(db, current_user.user_id),
        action="update", module="Branding",
        previous_value=previous.get("primary_color"), new_value=primary_color,
    )
    db.commit()
    return {"data": org.branding}


# ── Formula / Rule Configuration ─────────────────────────────────────────────
# Currently covers the Contractor Risk Score weights (the one formula that's
# both fully self-contained and safe to make per-org configurable without
# touching the shared workflow factory other scores are built on).

@router.get("/formula-config")
def get_formula_config(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)) -> dict:
    org = db.query(Organisation).filter(Organisation.id == current_user.org_id).first()
    saved = (org.formula_config or {}).get("contractor_score") if org and org.formula_config else None
    return {"data": {"contractor_score": {**DEFAULT_CONTRACTOR_WEIGHTS, **(saved or {})}}}


@router.put("/formula-config")
def save_formula_config(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    if not current_user.org_id:
        raise HTTPException(status_code=400, detail="No organisation on this account")
    org = db.query(Organisation).filter(Organisation.id == current_user.org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    incoming = payload.get("contractor_score") or {}
    try:
        weights = {k: float(incoming.get(k, v)) for k, v in DEFAULT_CONTRACTOR_WEIGHTS.items()}
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Weights must be numeric")
    for key in weights:
        if weights[key] < 0:
            raise HTTPException(status_code=400, detail=f"{key} cannot be negative")

    previous = (org.formula_config or {}).get("contractor_score") if org.formula_config else DEFAULT_CONTRACTOR_WEIGHTS
    org.formula_config = {**(org.formula_config or {}), "contractor_score": weights}
    record_audit(
        db, current_user.org_id, resolve_employee_id(db, current_user.user_id),
        action="update", module="Formula Config", record_id="contractor_score",
        previous_value=str(previous), new_value=str(weights),
    )
    db.commit()
    return {"data": {"contractor_score": weights}}


# ── Rating Labels ─────────────────────────────────────────────────────────────
# Wording (and cutoffs) for the two rating vocabularies used across the
# People, Compliance and Assets pages — "Excellent/Good/Needs Improvement" and
# "Low/Medium/High Risk". Different industries read these words differently,
# so an org admin can rename the bands here instead of them being fixed in
# code. See app/services/rating_labels.py for how these are applied.

@router.get("/rating-labels")
def get_rating_labels_config(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)) -> dict:
    org = db.query(Organisation).filter(Organisation.id == current_user.org_id).first()
    saved = (org.formula_config or {}).get("rating_labels") if org and org.formula_config else None
    return {
        "data": {
            scale: {**defaults, **((saved or {}).get(scale) or {})}
            for scale, defaults in DEFAULT_RATING_LABELS.items()
        }
    }


@router.put("/rating-labels")
def save_rating_labels_config(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    if not current_user.org_id:
        raise HTTPException(status_code=400, detail="No organisation on this account")
    org = db.query(Organisation).filter(Organisation.id == current_user.org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    scales = {}
    for scale, defaults in DEFAULT_RATING_LABELS.items():
        incoming = payload.get(scale) or {}
        try:
            high_floor = float(incoming.get("high_floor", defaults["high_floor"]))
            mid_floor = float(incoming.get("mid_floor", defaults["mid_floor"]))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{scale}: thresholds must be numeric")
        if high_floor <= mid_floor:
            raise HTTPException(status_code=400, detail=f"{scale}: the high threshold must be above the mid threshold")
        high_label = str(incoming.get("high_label", defaults["high_label"])).strip()
        mid_label = str(incoming.get("mid_label", defaults["mid_label"])).strip()
        low_label = str(incoming.get("low_label", defaults["low_label"])).strip()
        if not (high_label and mid_label and low_label):
            raise HTTPException(status_code=400, detail=f"{scale}: labels cannot be empty")
        scales[scale] = {
            "high_floor": high_floor, "high_label": high_label,
            "mid_floor": mid_floor, "mid_label": mid_label,
            "low_label": low_label,
        }

    previous = (org.formula_config or {}).get("rating_labels")
    org.formula_config = {**(org.formula_config or {}), "rating_labels": scales}
    record_audit(
        db, current_user.org_id, resolve_employee_id(db, current_user.user_id),
        action="update", module="Rating Labels",
        previous_value=str(previous), new_value=str(scales),
    )
    db.commit()
    return {"data": scales}


# ── Audit Trail ───────────────────────────────────────────────────────────────

@router.get("/audit-logs")
def list_audit_logs(
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    from app.models.employee import Employee

    rows = (
        db.query(AuditLog, Employee.full_name)
        .outerjoin(Employee, org_scoped_join(AuditLog.employee_id == Employee.id, Employee.organisation_id, current_user.org_id))
        .filter(AuditLog.organisation_id == current_user.org_id)
        .order_by(AuditLog.created_at.desc())
        .limit(min(limit, 500))
        .all()
    )
    return {
        "data": [
            {
                "id": log.id,
                "timestamp": log.created_at.isoformat() if log.created_at else "",
                "user": full_name or "System",
                "action": log.action,
                "module": log.module,
                "record_id": log.record_id,
                "previous_value": log.previous_value,
                "new_value": log.new_value,
                "ip_address": log.ip_address,
            }
            for log, full_name in rows
        ]
    }
