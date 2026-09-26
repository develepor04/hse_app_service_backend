"""
Full checklist controller — templates, submissions, items, logs.
Replaces the stub endpoints in stubs.py.
"""
import json
import uuid as _uuid
from datetime import datetime, timedelta
from typing import Any, Optional, List, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import (
    get_current_user,
    CurrentUser,
)
from app.controllers.workflow_common import require_role

router = APIRouter(prefix="/checklists", tags=["Checklists"])

# Templates are shared, platform-wide config (no organisation_id column) — every
# tenant sees the same checklist, so only admin-tier roles may edit one.
TEMPLATE_ADMIN_ROLES = {"admin", "hse manager", "superadmin"}

# ─── helpers ─────────────────────────────────────────────────────────────────

def _actor(request: Request, current_user: CurrentUser):
    return current_user.email, current_user.role


def _tmpl(db: Session, checklist_type: str) -> dict:
    row = db.execute(
        text("SELECT * FROM checklist_templates WHERE checklist_type = :t AND is_active = 1"),
        {"t": checklist_type},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Template '{checklist_type}' not found")
    return dict(row)


def _sub(db: Session, submission_uuid: str, org_id: Optional[int] = None) -> dict:
    """Look up a submission by its UUID.

    checklist_submissions carries no organisation_id of its own — the only
    tenant link is site_id -> sites.organisation_id. When org_id is given,
    that join is checked so a UUID for another org's submission (guessed or
    enumerated) 404s instead of returning cross-tenant checklist data.
    """
    if org_id is not None:
        row = db.execute(
            text(
                "SELECT cs.* FROM checklist_submissions cs "
                "JOIN sites s ON cs.site_id = s.id "
                "WHERE cs.submission_uuid = :u AND s.organisation_id = :org_id"
            ),
            {"u": submission_uuid, "org_id": org_id},
        ).mappings().first()
    else:
        row = db.execute(
            text("SELECT * FROM checklist_submissions WHERE submission_uuid = :u"),
            {"u": submission_uuid},
        ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Submission not found")
    return dict(row)


def _fmt_tmpl(row: dict) -> dict:
    return {
        "checklist_type": row["checklist_type"],
        "display_name":   row["display_name"],
        "description":    row.get("description"),
        "submitter_roles": json.loads(row["submitter_roles"]),
        "validator_roles": json.loads(row["validator_roles"]),
        "items":           json.loads(row["items_json"]),
        "item_count":      len(json.loads(row["items_json"])),
        "ui":   json.loads(row["ui_json"])  if row.get("ui_json")  else None,
        "sla":  json.loads(row["sla_json"]) if row.get("sla_json") else None,
    }


def _fmt_sub(row: dict) -> dict:
    return {
        "submission_uuid":      row["submission_uuid"],
        "checklist_type":       row["checklist_type"],
        "site_id":              row.get("site_id"),
        "zone_id":              row.get("zone_id"),
        "shift_name":           row.get("shift_name"),
        "checklist_date":       str(row["checklist_date"]),
        "submitted_by_email":   row.get("submitted_by_email", ""),
        "submitted_by_role":    row.get("submitted_by_role", ""),
        "status":               row["status"],
        "created_at":           str(row["created_at"]),
        "updated_at":           str(row["updated_at"]),
        "submit_due_at":        str(row["submit_due_at"]) if row.get("submit_due_at") else None,
        "validate_due_at":      str(row["validate_due_at"]) if row.get("validate_due_at") else None,
        "submit_sla_breached":  row.get("submit_sla_breached", 0),
        "validate_sla_breached":row.get("validate_sla_breached", 0),
        "validation_decision":  row.get("validation_decision"),
        "validation_notes":     row.get("validation_notes"),
    }


# ─── templates ───────────────────────────────────────────────────────────────

@router.get("/templates")
def list_templates(db: Session = Depends(get_db)) -> list:
    rows = db.execute(
        text("SELECT * FROM checklist_templates WHERE is_active = 1 ORDER BY display_name")
    ).mappings().all()
    return [_fmt_tmpl(dict(r)) for r in rows]


@router.post("/templates/bootstrap")
def bootstrap_templates(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)) -> dict:
    """Seed the six default HSE checklist templates."""
    templates = _default_templates()
    counts: Dict[str, int] = {}
    for t in templates:
        existing = db.execute(
            text("SELECT id FROM checklist_templates WHERE checklist_type = :t"),
            {"t": t["checklist_type"]},
        ).first()
        if existing:
            counts[t["checklist_type"]] = 0
            continue
        db.execute(text("""
            INSERT INTO checklist_templates
                (checklist_type, display_name, submitter_roles, validator_roles,
                 items_json, ui_json, sla_json)
            VALUES (:ct, :dn, :sr, :vr, :ij, :uj, :sj)
        """), {
            "ct": t["checklist_type"],
            "dn": t["display_name"],
            "sr": json.dumps(t["submitter_roles"]),
            "vr": json.dumps(t["validator_roles"]),
            "ij": json.dumps(t["items"]),
            "uj": json.dumps(t.get("ui")) if t.get("ui") else None,
            "sj": json.dumps(t.get("sla")) if t.get("sla") else None,
        })
        counts[t["checklist_type"]] = len(t["items"])
    db.commit()
    return {"status": "ok", "message": "Templates bootstrapped", "counts": counts}


def _slugify(display_name: str) -> str:
    slug = "".join(c.lower() if c.isalnum() else "_" for c in display_name.strip())
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "checklist"


@router.post("/templates", status_code=status.HTTP_201_CREATED)
def create_template(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Create a new checklist template — lets an HSE Manager/Admin define a checklist
    from the web app instead of it being fixed in code."""
    require_role(current_user.role, TEMPLATE_ADMIN_ROLES, "create a checklist template")
    display_name = (payload.get("display_name") or "").strip()
    items = payload.get("items") or []
    if not display_name:
        raise HTTPException(status_code=400, detail="display_name is required")
    if not items:
        raise HTTPException(status_code=400, detail="At least one checklist item is required")

    checklist_type = (payload.get("checklist_type") or "").strip() or _slugify(display_name)
    existing = db.execute(
        text("SELECT id FROM checklist_templates WHERE checklist_type = :t"),
        {"t": checklist_type},
    ).first()
    if existing:
        suffix = 2
        base = checklist_type
        while existing:
            checklist_type = f"{base}_{suffix}"
            existing = db.execute(
                text("SELECT id FROM checklist_templates WHERE checklist_type = :t"),
                {"t": checklist_type},
            ).first()
            suffix += 1

    submitter_roles = payload.get("submitter_roles") or ["Admin", "HSE Manager", "Supervisor"]
    validator_roles = payload.get("validator_roles") or ["Admin", "HSE Manager"]
    normalized_items = [
        {
            "section_name": item.get("section_name") or "General",
            "item_no": i + 1,
            "item_text": item.get("item_text", ""),
            "is_required": bool(item.get("is_required", True)),
        }
        for i, item in enumerate(items)
        if (item.get("item_text") or "").strip()
    ]
    if not normalized_items:
        raise HTTPException(status_code=400, detail="At least one checklist item with text is required")

    ui = {"form_title": display_name, "short_label": display_name[:24], "version_tag": "v1.0"}
    description = (payload.get("description") or "").strip() or None

    sla_in = payload.get("sla") or {}
    sla = {
        "draft_submission_sla_hours": int(sla_in.get("draft_submission_sla_hours", 24)),
        "validation_sla_hours": int(sla_in.get("validation_sla_hours", 48)),
    }

    db.execute(text("""
        INSERT INTO checklist_templates
            (checklist_type, display_name, submitter_roles, validator_roles,
             items_json, ui_json, description, sla_json)
        VALUES (:ct, :dn, :sr, :vr, :ij, :uj, :de, :sj)
    """), {
        "ct": checklist_type,
        "dn": display_name,
        "sr": json.dumps(submitter_roles),
        "vr": json.dumps(validator_roles),
        "ij": json.dumps(normalized_items),
        "uj": json.dumps(ui),
        "de": description,
        "sj": json.dumps(sla),
    })
    db.commit()

    row = db.execute(
        text("SELECT * FROM checklist_templates WHERE checklist_type = :t"),
        {"t": checklist_type},
    ).mappings().first()
    return _fmt_tmpl(dict(row))


@router.put("/templates/{checklist_type}")
def update_template(
    checklist_type: str,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    require_role(current_user.role, TEMPLATE_ADMIN_ROLES, "edit a checklist template")
    row = db.execute(
        text("SELECT * FROM checklist_templates WHERE checklist_type = :t"),
        {"t": checklist_type},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Template '{checklist_type}' not found")

    display_name = (payload.get("display_name") or row["display_name"]).strip()
    items = payload.get("items")
    if items is not None:
        normalized_items = [
            {
                "section_name": item.get("section_name") or "General",
                "item_no": i + 1,
                "item_text": item.get("item_text", ""),
                "is_required": bool(item.get("is_required", True)),
            }
            for i, item in enumerate(items)
            if (item.get("item_text") or "").strip()
        ]
        if not normalized_items:
            raise HTTPException(status_code=400, detail="At least one checklist item with text is required")
        items_json = json.dumps(normalized_items)
    else:
        items_json = row["items_json"]

    submitter_roles = payload.get("submitter_roles") or json.loads(row["submitter_roles"])
    validator_roles = payload.get("validator_roles") or json.loads(row["validator_roles"])
    description = payload.get("description", row.get("description"))

    existing_sla = json.loads(row["sla_json"]) if row.get("sla_json") else {}
    sla_in = payload.get("sla") or {}
    sla = {
        "draft_submission_sla_hours": int(sla_in.get("draft_submission_sla_hours", existing_sla.get("draft_submission_sla_hours", 24))),
        "validation_sla_hours": int(sla_in.get("validation_sla_hours", existing_sla.get("validation_sla_hours", 48))),
    }

    db.execute(text("""
        UPDATE checklist_templates
        SET display_name = :dn, submitter_roles = :sr, validator_roles = :vr,
            items_json = :ij, description = :de, sla_json = :sj, updated_at = :ua
        WHERE checklist_type = :t
    """), {
        "dn": display_name, "sr": json.dumps(submitter_roles), "vr": json.dumps(validator_roles),
        "ij": items_json, "de": description, "sj": json.dumps(sla), "ua": datetime.utcnow(), "t": checklist_type,
    })
    db.commit()

    updated = db.execute(
        text("SELECT * FROM checklist_templates WHERE checklist_type = :t"),
        {"t": checklist_type},
    ).mappings().first()
    return _fmt_tmpl(dict(updated))


@router.delete("/templates/{checklist_type}")
def deactivate_template(
    checklist_type: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Soft-delete — keeps history of past submissions against this template intact."""
    require_role(current_user.role, TEMPLATE_ADMIN_ROLES, "deactivate a checklist template")
    db.execute(
        text("UPDATE checklist_templates SET is_active = 0 WHERE checklist_type = :t"),
        {"t": checklist_type},
    )
    db.commit()
    return {"deactivated": True}


# ─── submissions ──────────────────────────────────────────────────────────────

@router.get("/submissions")
def list_submissions(
    limit: int = Query(20, le=1000),
    checklist_type: Optional[str] = None,
    status: Optional[str] = None,
    mine: bool = False,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> list:
    where = "WHERE 1=1"
    params: Dict[str, Any] = {"limit": limit}
    if checklist_type:
        where += " AND checklist_type = :ct"
        params["ct"] = checklist_type
    if status:
        where += " AND status = :st"
        params["st"] = status
    if mine:
        # Own history — scoped to the caller, so the org filter below is redundant.
        where += " AND submitted_by_email = :actor_email"
        params["actor_email"] = current_user.email
    elif current_user.org_id is not None:
        where += " AND submitted_by_email IN (SELECT email FROM users WHERE organisation_id = :org_id)"
        params["org_id"] = current_user.org_id
    rows = db.execute(
        text(f"SELECT * FROM checklist_submissions {where} ORDER BY created_at DESC LIMIT :limit"),
        params,
    ).mappings().all()
    return [_fmt_sub(dict(r)) for r in rows]


@router.post("/submissions", status_code=status.HTTP_201_CREATED)
def create_submission(
    request: Request,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    checklist_type = payload.get("checklist_type", "")
    tmpl = _tmpl(db, checklist_type)
    items = json.loads(tmpl["items_json"])
    sla   = json.loads(tmpl["sla_json"]) if tmpl.get("sla_json") else {}

    site_id = payload.get("site_id")
    if site_id is not None:
        site_in_org = db.execute(
            text("SELECT id FROM sites WHERE id = :id AND organisation_id = :org_id"),
            {"id": site_id, "org_id": current_user.org_id},
        ).scalar()
        if not site_in_org:
            raise HTTPException(status_code=404, detail="No such site")

    sub_uuid = str(_uuid.uuid4())
    now  = datetime.utcnow()
    cdate = payload.get("checklist_date") or now.date().isoformat()
    actor_email, actor_role = _actor(request, current_user)

    submit_sla_h = sla.get("draft_submission_sla_hours", 24) if sla else 24
    submit_due = now + timedelta(hours=submit_sla_h)

    db.execute(text("""
        INSERT INTO checklist_submissions
            (submission_uuid, checklist_type, site_id, zone_id, shift_name,
             checklist_date, submitted_by_email, submitted_by_role, status, submit_due_at)
        VALUES (:u, :ct, :si, :zi, :sh, :cd, :em, :ro, 'draft', :sd)
    """), {
        "u": sub_uuid, "ct": checklist_type,
        "si": payload.get("site_id"), "zi": payload.get("zone_id"),
        "sh": payload.get("shift_name"),
        "cd": cdate, "em": actor_email, "ro": actor_role, "sd": submit_due,
    })

    # Copy template items into submission items
    for item in items:
        db.execute(text("""
            INSERT INTO checklist_submission_items
                (submission_uuid, item_no, section_name, item_text, is_required)
            VALUES (:u, :no, :sn, :it, :ir)
        """), {
            "u": sub_uuid, "no": item["item_no"],
            "sn": item["section_name"], "it": item["item_text"],
            "ir": 1 if item.get("is_required") else 0,
        })

    # Log creation
    db.execute(text("""
        INSERT INTO checklist_logs (submission_uuid, action_type, actor_email, actor_role, to_status)
        VALUES (:u, 'created', :em, :ro, 'draft')
    """), {"u": sub_uuid, "em": actor_email, "ro": actor_role})

    db.commit()
    return {"submission_uuid": sub_uuid, "status": "draft", "submit_due_at": str(submit_due)}


@router.get("/submissions/{submission_uuid}")
def get_submission(submission_uuid: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)) -> dict:
    sub  = _sub(db, submission_uuid, current_user.org_id)
    tmpl = _tmpl(db, sub["checklist_type"])

    items = db.execute(
        text("SELECT * FROM checklist_submission_items WHERE submission_uuid = :u ORDER BY item_no"),
        {"u": submission_uuid},
    ).mappings().all()

    logs = db.execute(
        text("SELECT * FROM checklist_logs WHERE submission_uuid = :u ORDER BY created_at"),
        {"u": submission_uuid},
    ).mappings().all()

    def _fmt_item(r: dict) -> dict:
        return {
            "item_no":         r["item_no"],
            "section_name":    r["section_name"],
            "item_text":       r["item_text"],
            "is_required":     r["is_required"],
            "response_value":  r.get("response_value"),
            "remark":          r.get("remark"),
            "evidence_json":   r.get("evidence_json"),
            "updated_by_email":r.get("updated_by_email"),
            "updated_by_role": r.get("updated_by_role"),
            "updated_at":      str(r["updated_at"]) if r.get("updated_at") else None,
        }

    def _fmt_log(r: dict) -> dict:
        return {
            "action_type": r["action_type"],
            "actor_email": r.get("actor_email", ""),
            "actor_role":  r.get("actor_role", ""),
            "from_status": r.get("from_status"),
            "to_status":   r.get("to_status"),
            "notes":       r.get("notes"),
            "created_at":  str(r["created_at"]),
        }

    return {
        "submission": _fmt_sub(sub),
        "template": {
            "checklist_type":  tmpl["checklist_type"],
            "display_name":    tmpl["display_name"],
            "submitter_roles": json.loads(tmpl["submitter_roles"]),
            "validator_roles": json.loads(tmpl["validator_roles"]),
            "ui":  json.loads(tmpl["ui_json"])  if tmpl.get("ui_json")  else None,
            "sla": json.loads(tmpl["sla_json"]) if tmpl.get("sla_json") else None,
        },
        "items": [_fmt_item(dict(r)) for r in items],
        "logs":  [_fmt_log(dict(r))  for r in logs],
    }


@router.put("/submissions/{submission_uuid}/items")
def save_items(
    submission_uuid: str,
    request: Request,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    sub = _sub(db, submission_uuid, current_user.org_id)
    if sub["status"] != "draft":
        raise HTTPException(status_code=400, detail="Only draft submissions can be edited")

    actor_email, actor_role = _actor(request, current_user)
    items = payload.get("items", [])
    now = datetime.utcnow()

    for item in items:
        db.execute(text("""
            UPDATE checklist_submission_items
            SET response_value = :rv, remark = :rm,
                updated_by_email = :em, updated_by_role = :ro, updated_at = :ua
            WHERE submission_uuid = :u AND item_no = :no
        """), {
            "rv": item.get("response_value"), "rm": item.get("remark"),
            "em": actor_email, "ro": actor_role, "ua": now,
            "u": submission_uuid, "no": item["item_no"],
        })
    db.commit()
    return {"status": "saved", "updated_items": len(items)}


@router.post("/submissions/{submission_uuid}/submit")
def submit_submission(
    submission_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    sub = _sub(db, submission_uuid, current_user.org_id)
    if sub["status"] != "draft":
        raise HTTPException(status_code=400, detail="Only draft submissions can be submitted")

    actor_email, actor_role = _actor(request, current_user)
    tmpl = _tmpl(db, sub["checklist_type"])
    sla = json.loads(tmpl["sla_json"]) if tmpl.get("sla_json") else {}
    validate_sla_h = sla.get("validation_sla_hours", 48) if sla else 48
    validate_due = datetime.utcnow() + timedelta(hours=validate_sla_h)

    db.execute(text("""
        UPDATE checklist_submissions
        SET status = 'submitted', validate_due_at = :vd, updated_at = :ua
        WHERE submission_uuid = :u
    """), {"vd": validate_due, "ua": datetime.utcnow(), "u": submission_uuid})

    db.execute(text("""
        INSERT INTO checklist_logs (submission_uuid, action_type, actor_email, actor_role, from_status, to_status)
        VALUES (:u, 'submitted', :em, :ro, 'draft', 'submitted')
    """), {"u": submission_uuid, "em": actor_email, "ro": actor_role})

    db.commit()
    return {"status": "submitted", "submission_uuid": submission_uuid}


@router.post("/submissions/{submission_uuid}/validate")
def validate_submission(submission_uuid: str, request: Request, payload: dict, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)) -> dict:
    sub = _sub(db, submission_uuid, current_user.org_id)
    if sub["status"] != "submitted":
        raise HTTPException(status_code=400, detail="Only submitted checklists can be validated")

    tmpl = _tmpl(db, sub["checklist_type"])
    require_role(current_user.role, set(json.loads(tmpl["validator_roles"])), "validate this checklist")

    decision = payload.get("decision", "approved")
    if decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision must be 'approved' or 'rejected'")

    actor_email, actor_role = _actor(request, current_user)
    new_status = "validated" if decision == "approved" else "rejected"
    notes = payload.get("notes")

    db.execute(text("""
        UPDATE checklist_submissions
        SET status = :ns, validation_decision = :vd, validation_notes = :vn, updated_at = :ua
        WHERE submission_uuid = :u
    """), {
        "ns": new_status, "vd": decision, "vn": notes,
        "ua": datetime.utcnow(), "u": submission_uuid,
    })

    db.execute(text("""
        INSERT INTO checklist_logs
            (submission_uuid, action_type, actor_email, actor_role, from_status, to_status, notes)
        VALUES (:u, :at, :em, :ro, 'submitted', :ns, :no)
    """), {
        "u": submission_uuid, "at": f"validation_{decision}",
        "em": actor_email, "ro": actor_role, "ns": new_status, "no": notes,
    })

    db.commit()
    return {"status": new_status, "submission_uuid": submission_uuid}


# ─── default templates ────────────────────────────────────────────────────────

def _default_templates() -> List[dict]:
    all_roles = ["Admin", "HSE Manager", "Safety Manager", "Supervisor", "Site Inspector", "Site Engineer", "Auditor"]
    admin_validator = ["Admin", "HSE Manager"]

    return [
        {
            "checklist_type": "daily_safety_walk",
            "display_name":   "Daily Safety Walk",
            "submitter_roles": ["Admin", "Site Inspector", "Safety Manager", "Supervisor"],
            "validator_roles": admin_validator,
            "ui":  {"form_title": "Daily Safety Walk Inspection", "short_label": "Safety Walk", "version_tag": "v1.0"},
            "sla": {"draft_submission_sla_hours": 12, "validation_sla_hours": 24},
            "items": [
                {"section_name": "PPE & Clothing",       "item_no": 1,  "item_text": "All workers in the area are wearing appropriate hard hats",            "is_required": True},
                {"section_name": "PPE & Clothing",       "item_no": 2,  "item_text": "High-visibility vests are worn by all personnel on site",              "is_required": True},
                {"section_name": "PPE & Clothing",       "item_no": 3,  "item_text": "Safety footwear (steel toe-cap) is worn by all workers",               "is_required": True},
                {"section_name": "PPE & Clothing",       "item_no": 4,  "item_text": "Appropriate gloves are available and being used where required",        "is_required": False},
                {"section_name": "PPE & Clothing",       "item_no": 5,  "item_text": "Eye protection is worn in designated zones",                           "is_required": False},
                {"section_name": "Housekeeping",         "item_no": 6,  "item_text": "Walkways and emergency exits are clear of obstructions",                "is_required": True},
                {"section_name": "Housekeeping",         "item_no": 7,  "item_text": "Waste materials are disposed of in correct containers",                 "is_required": False},
                {"section_name": "Housekeeping",         "item_no": 8,  "item_text": "Spillage kits are in place and accessible",                            "is_required": False},
                {"section_name": "Fire Safety",          "item_no": 9,  "item_text": "Fire extinguishers are present, charged and accessible",               "is_required": True},
                {"section_name": "Fire Safety",          "item_no": 10, "item_text": "Fire assembly point is clearly marked and unobstructed",                "is_required": True},
                {"section_name": "Fire Safety",          "item_no": 11, "item_text": "No smoking in designated non-smoking areas",                           "is_required": False},
                {"section_name": "Hazard Signage",       "item_no": 12, "item_text": "All hazard warning signs are visible and in good condition",            "is_required": True},
                {"section_name": "Hazard Signage",       "item_no": 13, "item_text": "Restricted access zones are clearly demarcated",                       "is_required": True},
                {"section_name": "Emergency Equipment",  "item_no": 14, "item_text": "First aid kit is fully stocked and accessible",                        "is_required": True},
                {"section_name": "Emergency Equipment",  "item_no": 15, "item_text": "Emergency contact numbers are posted in visible locations",             "is_required": False},
            ],
        },
        {
            "checklist_type": "ppe_compliance_audit",
            "display_name":   "PPE Compliance Audit",
            "submitter_roles": ["Admin", "Site Inspector", "Safety Manager", "Supervisor", "Auditor"],
            "validator_roles": admin_validator,
            "ui":  {"form_title": "PPE Compliance Audit", "short_label": "PPE Audit", "version_tag": "v1.0"},
            "sla": {"draft_submission_sla_hours": 8, "validation_sla_hours": 24},
            "items": [
                {"section_name": "Head Protection",      "item_no": 1,  "item_text": "EN397 hard hats present for all workers in mandatory zones",            "is_required": True},
                {"section_name": "Head Protection",      "item_no": 2,  "item_text": "Hard hats are free from damage, cracks or degradation",                 "is_required": True},
                {"section_name": "Eye & Face",           "item_no": 3,  "item_text": "Safety glasses / goggles available in grinding and chemical zones",      "is_required": True},
                {"section_name": "Eye & Face",           "item_no": 4,  "item_text": "Face shields are available for chemical handling tasks",                 "is_required": False},
                {"section_name": "Hearing Protection",   "item_no": 5,  "item_text": "Ear defenders or plugs available in areas exceeding 85 dB",              "is_required": True},
                {"section_name": "Hand Protection",      "item_no": 6,  "item_text": "Cut-resistant gloves available for sheet metal work",                   "is_required": True},
                {"section_name": "Hand Protection",      "item_no": 7,  "item_text": "Chemical-resistant gloves available at chemical storage areas",          "is_required": True},
                {"section_name": "Foot Protection",      "item_no": 8,  "item_text": "Steel toe-cap boots (S3) worn by all workers on production floor",       "is_required": True},
                {"section_name": "Body Protection",      "item_no": 9,  "item_text": "Hi-vis vest EN ISO 20471 Class 2 worn outdoors and in vehicle zones",    "is_required": True},
                {"section_name": "Body Protection",      "item_no": 10, "item_text": "Flame-retardant clothing worn by workers performing hot work",           "is_required": False},
                {"section_name": "Fall Protection",      "item_no": 11, "item_text": "Full-body harness available and inspected for WAH tasks",               "is_required": True},
                {"section_name": "Fall Protection",      "item_no": 12, "item_text": "Harnesses have valid inspection date tag (within 6 months)",             "is_required": True},
                {"section_name": "Respiratory",          "item_no": 13, "item_text": "Respiratory protection available in chemical and dust areas",             "is_required": False},
                {"section_name": "Respiratory",          "item_no": 14, "item_text": "RPE fit-test records available for assigned users",                     "is_required": False},
            ],
        },
        {
            "checklist_type": "hot_work_pre_task",
            "display_name":   "Hot Work Pre-Task Checklist",
            "submitter_roles": ["Admin", "Supervisor", "Site Engineer", "Safety Manager"],
            "validator_roles": admin_validator,
            "ui":  {"form_title": "Hot Work Pre-Task Safety Check", "short_label": "Hot Work", "version_tag": "v1.0"},
            "sla": {"draft_submission_sla_hours": 4, "validation_sla_hours": 8},
            "items": [
                {"section_name": "Permit",               "item_no": 1,  "item_text": "Valid Hot Work Permit is displayed at the work location",               "is_required": True},
                {"section_name": "Permit",               "item_no": 2,  "item_text": "Permit validity period has been confirmed and not expired",              "is_required": True},
                {"section_name": "Area Preparation",     "item_no": 3,  "item_text": "All combustible materials removed or shielded within 5m radius",         "is_required": True},
                {"section_name": "Area Preparation",     "item_no": 4,  "item_text": "Drains and openings are covered to prevent sparks entering",             "is_required": True},
                {"section_name": "Area Preparation",     "item_no": 5,  "item_text": "Adjacent areas on opposite side of barrier checked for combustibles",    "is_required": False},
                {"section_name": "Fire Prevention",      "item_no": 6,  "item_text": "CO2 or dry powder extinguisher (min 9kg) positioned at work site",       "is_required": True},
                {"section_name": "Fire Prevention",      "item_no": 7,  "item_text": "Fire watch operative assigned and briefed on duties",                    "is_required": True},
                {"section_name": "Fire Prevention",      "item_no": 8,  "item_text": "Fire watch to continue for minimum 30 minutes after work completion",    "is_required": True},
                {"section_name": "Atmosphere Check",     "item_no": 9,  "item_text": "Atmosphere tested for flammable gases — result recorded (LEL < 5%)",     "is_required": True},
                {"section_name": "Atmosphere Check",     "item_no": 10, "item_text": "Ventilation is adequate to remove fumes and maintain safe atmosphere",   "is_required": True},
                {"section_name": "Operator PPE",         "item_no": 11, "item_text": "Welder wearing flame-retardant overalls, gloves, shield and footwear",   "is_required": True},
                {"section_name": "Operator PPE",         "item_no": 12, "item_text": "No synthetic clothing under FR overalls",                               "is_required": False},
                {"section_name": "Close-out",            "item_no": 13, "item_text": "All equipment isolated and made safe on completion",                    "is_required": True},
                {"section_name": "Close-out",            "item_no": 14, "item_text": "Permit signed off and filed after work completion",                     "is_required": True},
            ],
        },
        {
            "checklist_type": "working_at_height",
            "display_name":   "Working at Height Checklist",
            "submitter_roles": ["Admin", "Supervisor", "Site Engineer", "Site Inspector", "Safety Manager"],
            "validator_roles": admin_validator,
            "ui":  {"form_title": "Working at Height Pre-Task Check", "short_label": "WAH Check", "version_tag": "v1.0"},
            "sla": {"draft_submission_sla_hours": 4, "validation_sla_hours": 12},
            "items": [
                {"section_name": "Permit & Planning",    "item_no": 1,  "item_text": "WAH Permit to Work is valid and displayed at the work location",         "is_required": True},
                {"section_name": "Permit & Planning",    "item_no": 2,  "item_text": "Method statement / risk assessment reviewed by all operatives",           "is_required": True},
                {"section_name": "Scaffold & Access",    "item_no": 3,  "item_text": "Scaffold has current inspection tag (inspected within 7 days)",           "is_required": True},
                {"section_name": "Scaffold & Access",    "item_no": 4,  "item_text": "All scaffold boards are fully supported with no overhang gaps",           "is_required": True},
                {"section_name": "Scaffold & Access",    "item_no": 5,  "item_text": "Guard rails (min 950mm), mid-rails and toe-boards fitted",                "is_required": True},
                {"section_name": "Scaffold & Access",    "item_no": 6,  "item_text": "Ladder secured and extending 1m above landing point",                    "is_required": False},
                {"section_name": "Fall Protection",      "item_no": 7,  "item_text": "Full-body harness worn and connected to rated anchor point",              "is_required": True},
                {"section_name": "Fall Protection",      "item_no": 8,  "item_text": "Lanyard / PFPE has been inspected and is in-date",                       "is_required": True},
                {"section_name": "Fall Protection",      "item_no": 9,  "item_text": "Fall rescue plan communicated to all on site",                           "is_required": True},
                {"section_name": "Exclusion Zone",       "item_no": 10, "item_text": "Exclusion zone below work area is barriered and signed",                  "is_required": True},
                {"section_name": "Exclusion Zone",       "item_no": 11, "item_text": "Banksman / spotter present if overhead work near traffic or public",      "is_required": False},
                {"section_name": "Weather & Environment","item_no": 12, "item_text": "Wind speed checked — work suspended if > 15m/s (Force 7)",                "is_required": True},
                {"section_name": "Weather & Environment","item_no": 13, "item_text": "Surfaces checked for ice, wet or slippery conditions",                    "is_required": True},
                {"section_name": "Tools & Equipment",    "item_no": 14, "item_text": "All tools tethered or contained to prevent dropped objects",              "is_required": True},
                {"section_name": "Tools & Equipment",    "item_no": 15, "item_text": "No loose materials stored at height — secured or removed before work",    "is_required": False},
            ],
        },
        {
            "checklist_type": "confined_space_entry",
            "display_name":   "Confined Space Entry Checklist",
            "submitter_roles": ["Admin", "Supervisor", "Site Engineer", "Safety Manager"],
            "validator_roles": admin_validator,
            "ui":  {"form_title": "Confined Space Entry Check", "short_label": "Confined Space", "version_tag": "v1.0"},
            "sla": {"draft_submission_sla_hours": 2, "validation_sla_hours": 8},
            "items": [
                {"section_name": "Permit",               "item_no": 1,  "item_text": "Confined Space Entry Permit is signed and displayed",                    "is_required": True},
                {"section_name": "Permit",               "item_no": 2,  "item_text": "All entrants and standby named on the permit",                           "is_required": True},
                {"section_name": "Atmosphere Testing",   "item_no": 3,  "item_text": "Oxygen level tested: 19.5%–23.5% (safe range)",                          "is_required": True},
                {"section_name": "Atmosphere Testing",   "item_no": 4,  "item_text": "Flammable gas/vapour tested: < 5% LEL",                                  "is_required": True},
                {"section_name": "Atmosphere Testing",   "item_no": 5,  "item_text": "Toxic gases (CO, H2S) tested — results within safe limits",               "is_required": True},
                {"section_name": "Atmosphere Testing",   "item_no": 6,  "item_text": "Continuous gas monitoring in use for the duration of entry",              "is_required": True},
                {"section_name": "Isolation",            "item_no": 7,  "item_text": "All pipework and services isolated with blanks or spades — LOTO applied", "is_required": True},
                {"section_name": "Isolation",            "item_no": 8,  "item_text": "Mechanical agitators / mixing equipment locked out",                     "is_required": True},
                {"section_name": "Rescue",               "item_no": 9,  "item_text": "Rescue harness and retrieval line rigged before entry",                  "is_required": True},
                {"section_name": "Rescue",               "item_no": 10, "item_text": "Trained standby man positioned at entry point for full duration",         "is_required": True},
                {"section_name": "Rescue",               "item_no": 11, "item_text": "Emergency services / on-site first aider informed and on standby",        "is_required": True},
                {"section_name": "Ventilation & Comms",  "item_no": 12, "item_text": "Forced ventilation equipment operating prior to entry",                   "is_required": True},
                {"section_name": "Ventilation & Comms",  "item_no": 13, "item_text": "Two-way communication between entrant and standby confirmed working",     "is_required": True},
                {"section_name": "PPE",                  "item_no": 14, "item_text": "Entrant wearing full-body harness, hard hat and appropriate RPE",         "is_required": True},
                {"section_name": "PPE",                  "item_no": 15, "item_text": "Intrinsically safe lighting used inside confined space",                  "is_required": True},
            ],
        },
        {
            "checklist_type": "end_of_shift_handover",
            "display_name":   "End of Shift Handover",
            "submitter_roles": ["Admin", "Supervisor", "Safety Manager", "HSE Manager"],
            "validator_roles": admin_validator,
            "ui":  {"form_title": "End of Shift Safety Handover", "short_label": "Shift Handover", "version_tag": "v1.0"},
            "sla": {"draft_submission_sla_hours": 1, "validation_sla_hours": 12},
            "items": [
                {"section_name": "Incidents & Near Misses","item_no": 1,  "item_text": "All incidents and near misses reported and logged in the system",       "is_required": True},
                {"section_name": "Incidents & Near Misses","item_no": 2,  "item_text": "Immediate corrective actions taken for any incidents documented",       "is_required": True},
                {"section_name": "Permits",              "item_no": 3,  "item_text": "All open permits checked — expired permits cancelled and filed",          "is_required": True},
                {"section_name": "Permits",              "item_no": 4,  "item_text": "Incoming supervisor briefed on all active permits for next shift",        "is_required": True},
                {"section_name": "Equipment",            "item_no": 5,  "item_text": "All machinery and equipment made safe or isolated before shift end",      "is_required": True},
                {"section_name": "Equipment",            "item_no": 6,  "item_text": "Any defective equipment tagged out and maintenance informed",             "is_required": False},
                {"section_name": "Housekeeping",         "item_no": 7,  "item_text": "Work area clean and tidy — waste removed to designated points",           "is_required": False},
                {"section_name": "Housekeeping",         "item_no": 8,  "item_text": "Chemicals and hazardous materials stored securely in correct locations",  "is_required": True},
                {"section_name": "Personnel",            "item_no": 9,  "item_text": "All workers accounted for — headcount completed",                        "is_required": True},
                {"section_name": "Personnel",            "item_no": 10, "item_text": "Incoming shift supervisor briefed on outstanding hazards or risks",       "is_required": True},
                {"section_name": "Communication",        "item_no": 11, "item_text": "All CAPA actions updated with progress in the system",                   "is_required": False},
                {"section_name": "Communication",        "item_no": 12, "item_text": "Safety observations from this shift logged and forwarded",                "is_required": False},
            ],
        },
        # ══════════════════════════════════════════════════════════════════════
        # WORKER CHECKLISTS
        # ══════════════════════════════════════════════════════════════════════
        {
            "checklist_type": "worker_pre_shift",
            "display_name":   "Worker Pre-Shift / Pre-Task Checklist",
            "submitter_roles": ["Worker", "Employee", "Operator", "Technician"],
            "validator_roles": ["Supervisor", "Safety Manager"],
            "ui":  {"form_title": "Pre-Shift Safety Checklist", "short_label": "Pre-Shift", "version_tag": "v1.0"},
            "sla": {"draft_submission_sla_hours": 2, "validation_sla_hours": 12},
            "items": [
                {"section_name": "PPE",                  "item_no": 1,  "item_text": "PPE — Helmet, Gloves, Safety Boots, Vest, Goggles all worn correctly",    "is_required": True},
                {"section_name": "PPE",                  "item_no": 2,  "item_text": "Work Permit received and understood",                                    "is_required": True},
                {"section_name": "Tools & Equipment",    "item_no": 3,  "item_text": "Tool & Equipment condition check — no damage, calibrated",               "is_required": True},
                {"section_name": "Hazards",              "item_no": 4,  "item_text": "Work area hazards identified (slippery, overhead work, electrical)",      "is_required": True},
                {"section_name": "Emergency",            "item_no": 5,  "item_text": "Emergency exit location known",                                          "is_required": True},
                {"section_name": "Emergency",            "item_no": 6,  "item_text": "Fire Extinguisher accessible and charged",                               "is_required": True},
                {"section_name": "Emergency",            "item_no": 7,  "item_text": "First Aid kit location known",                                           "is_required": True},
                {"section_name": "Fitness",              "item_no": 8,  "item_text": "Feeling physically fit to work (no dizziness, no illness)",               "is_required": True},
                {"section_name": "Training",             "item_no": 9,  "item_text": "Toolbox Talk attended today",                                            "is_required": True},
                {"section_name": "Housekeeping",         "item_no": 10, "item_text": "Housekeeping — work area clean before starting",                          "is_required": True},
            ],
        },
        {
            "checklist_type": "worker_vehicle_pre_start",
            "display_name":   "Worker Vehicle / Equipment Pre-Start Check",
            "submitter_roles": ["Worker", "Employee", "Operator", "Technician"],
            "validator_roles": ["Supervisor", "Safety Manager"],
            "ui":  {"form_title": "Vehicle / Equipment Pre-Start Checklist", "short_label": "Vehicle Check", "version_tag": "v1.0"},
            "sla": {"draft_submission_sla_hours": 2, "validation_sla_hours": 12},
            "items": [
                {"section_name": "Braking",              "item_no": 1,  "item_text": "Braking Systems functional",                                             "is_required": True},
                {"section_name": "Tyres",                "item_no": 2,  "item_text": "Tyres & Wheels in good condition",                                       "is_required": True},
                {"section_name": "Lights",               "item_no": 3,  "item_text": "Lights & Indicators working",                                           "is_required": True},
                {"section_name": "Fire Safety",          "item_no": 4,  "item_text": "Fire Extinguisher present and charged",                                  "is_required": True},
                {"section_name": "Fluids",               "item_no": 5,  "item_text": "Fluid Levels (Oil, Water, Hydraulic) adequate",                          "is_required": True},
                {"section_name": "Visibility",           "item_no": 6,  "item_text": "Mirrors & Visibility clear and adjusted",                                "is_required": True},
                {"section_name": "Safety",               "item_no": 7,  "item_text": "Seatbelt functional",                                                   "is_required": True},
                {"section_name": "Safety",               "item_no": 8,  "item_text": "Horn functional",                                                       "is_required": True},
            ],
        },
        {
            "checklist_type": "worker_post_shift",
            "display_name":   "Worker Post-Shift / End-of-Day Checklist",
            "submitter_roles": ["Worker", "Employee", "Operator", "Technician"],
            "validator_roles": ["Supervisor", "Safety Manager"],
            "ui":  {"form_title": "Post-Shift Checklist", "short_label": "Post-Shift", "version_tag": "v1.0"},
            "sla": {"draft_submission_sla_hours": 1, "validation_sla_hours": 12},
            "items": [
                {"section_name": "Cleanup",              "item_no": 1,  "item_text": "Work area cleaned and hazards removed",                                  "is_required": True},
                {"section_name": "Tools",                "item_no": 2,  "item_text": "Tools returned and secured",                                             "is_required": True},
                {"section_name": "Reporting",            "item_no": 3,  "item_text": "Any incidents/near-misses occurred? (report if Yes)",                     "is_required": True},
                {"section_name": "Equipment",            "item_no": 4,  "item_text": "Any equipment damage found? (photo if Yes)",                             "is_required": True},
                {"section_name": "Waste",                "item_no": 5,  "item_text": "Waste disposed properly",                                                "is_required": True},
                {"section_name": "Permits",              "item_no": 6,  "item_text": "Work Permit closed",                                                     "is_required": True},
            ],
        },
        # ══════════════════════════════════════════════════════════════════════
        # SUPERVISOR CHECKLISTS
        # ══════════════════════════════════════════════════════════════════════
        {
            "checklist_type": "supervisor_morning_inspection",
            "display_name":   "Supervisor Morning Site Safety Inspection",
            "submitter_roles": ["Supervisor", "Site Inspector", "Safety Manager"],
            "validator_roles": admin_validator,
            "ui":  {"form_title": "Morning Site Safety Inspection", "short_label": "Morning Inspection", "version_tag": "v1.0"},
            "sla": {"draft_submission_sla_hours": 4, "validation_sla_hours": 24},
            "items": [
                {"section_name": "PPE Verification",     "item_no": 1,  "item_text": "All workers wearing correct PPE verified",                               "is_required": True},
                {"section_name": "Permits",              "item_no": 2,  "item_text": "Work Permits issued and valid for today's tasks",                        "is_required": True},
                {"section_name": "Training",             "item_no": 3,  "item_text": "Toolbox Talk conducted with team (record attendance count)",              "is_required": True},
                {"section_name": "Hazards",              "item_no": 4,  "item_text": "Hazardous area barricaded / signage in place",                           "is_required": True},
                {"section_name": "Emergency",            "item_no": 5,  "item_text": "Emergency assembly point communicated to team",                          "is_required": True},
                {"section_name": "Emergency",            "item_no": 6,  "item_text": "First Aid kit stocked and accessible",                                  "is_required": True},
                {"section_name": "Fire Safety",          "item_no": 7,  "item_text": "Fire extinguishers checked (location + pressure)",                       "is_required": True},
                {"section_name": "Hot Work",             "item_no": 8,  "item_text": "Hot work area controlled (if applicable)",                               "is_required": False},
                {"section_name": "Housekeeping",         "item_no": 9,  "item_text": "Housekeeping of site satisfactory",                                      "is_required": True},
                {"section_name": "Personnel",            "item_no": 10, "item_text": "All workers fit for duty (no signs of fatigue/substance)",                "is_required": True},
            ],
        },
        {
            "checklist_type": "supervisor_mid_shift",
            "display_name":   "Supervisor Mid-Shift Inspection",
            "submitter_roles": ["Supervisor", "Site Inspector", "Safety Manager"],
            "validator_roles": admin_validator,
            "ui":  {"form_title": "Mid-Shift Safety Inspection", "short_label": "Mid-Shift", "version_tag": "v1.0"},
            "sla": {"draft_submission_sla_hours": 4, "validation_sla_hours": 24},
            "items": [
                {"section_name": "Procedures",           "item_no": 1,  "item_text": "Workers following safe work procedures",                                 "is_required": True},
                {"section_name": "Access Control",       "item_no": 2,  "item_text": "No unauthorized personnel in work zone",                                 "is_required": True},
                {"section_name": "Equipment",            "item_no": 3,  "item_text": "Equipment/machinery being used correctly",                               "is_required": True},
                {"section_name": "Incidents",            "item_no": 4,  "item_text": "Any near-miss or incident occurred? (link to report)",                    "is_required": True},
                {"section_name": "Access Roads",         "item_no": 5,  "item_text": "Site access roads clear and safe",                                       "is_required": True},
                {"section_name": "Exposure",             "item_no": 6,  "item_text": "Noise/dust/chemical exposure within limits",                             "is_required": False},
                {"section_name": "Waste",                "item_no": 7,  "item_text": "Waste disposal being done correctly",                                    "is_required": True},
            ],
        },
        {
            "checklist_type": "supervisor_end_of_shift",
            "display_name":   "Supervisor End-of-Shift Closeout",
            "submitter_roles": ["Supervisor", "Site Inspector", "Safety Manager"],
            "validator_roles": admin_validator,
            "ui":  {"form_title": "End-of-Shift Closeout Checklist", "short_label": "Shift Closeout", "version_tag": "v1.0"},
            "sla": {"draft_submission_sla_hours": 1, "validation_sla_hours": 12},
            "items": [
                {"section_name": "Permits",              "item_no": 1,  "item_text": "All work permits closed",                                                "is_required": True},
                {"section_name": "Personnel",            "item_no": 2,  "item_text": "Headcount of all workers confirmed",                                     "is_required": True},
                {"section_name": "Equipment",            "item_no": 3,  "item_text": "Equipment shut down and secured",                                        "is_required": True},
                {"section_name": "Reporting",            "item_no": 4,  "item_text": "Incidents/near-misses reported to manager",                              "is_required": True},
                {"section_name": "Security",             "item_no": 5,  "item_text": "Site secured before leaving",                                            "is_required": True},
                {"section_name": "Planning",             "item_no": 6,  "item_text": "Tomorrow's work plan reviewed for hazards",                              "is_required": True},
            ],
        },
        {
            "checklist_type": "supervisor_weekly_observation",
            "display_name":   "Supervisor Weekly Team Safety Observation",
            "submitter_roles": ["Supervisor", "Site Inspector", "Safety Manager"],
            "validator_roles": admin_validator,
            "ui":  {"form_title": "Weekly Team Safety Observation", "short_label": "Weekly Obs", "version_tag": "v1.0"},
            "sla": {"draft_submission_sla_hours": 168, "validation_sla_hours": 48},
            "items": [
                {"section_name": "Observations",         "item_no": 1,  "item_text": "Number of safety observations raised this week (enter count)",           "is_required": True},
                {"section_name": "CAPA",                 "item_no": 2,  "item_text": "CAPA (Corrective Actions) closed on time",                               "is_required": True},
                {"section_name": "Training",             "item_no": 3,  "item_text": "Training compliance for team members (enter % score)",                   "is_required": True},
                {"section_name": "Culture",              "item_no": 4,  "item_text": "Near-miss reporting culture observed (rate 1-5)",                         "is_required": True},
            ],
        },
        # ══════════════════════════════════════════════════════════════════════
        # MANAGER CHECKLISTS
        # ══════════════════════════════════════════════════════════════════════
        {
            "checklist_type": "manager_daily_review",
            "display_name":   "Manager Daily Management Review",
            "submitter_roles": ["Manager", "HSE Manager", "Admin", "Director"],
            "validator_roles": admin_validator,
            "ui":  {"form_title": "Daily Management Review Checklist", "short_label": "Daily Review", "version_tag": "v1.0"},
            "sla": {"draft_submission_sla_hours": 8, "validation_sla_hours": 24},
            "items": [
                {"section_name": "Reports",              "item_no": 1,  "item_text": "All supervisors submitted morning inspection reports",                   "is_required": True},
                {"section_name": "Incidents",            "item_no": 2,  "item_text": "Any critical incidents in last 24 hours reviewed and actioned",          "is_required": True},
                {"section_name": "Permits",              "item_no": 3,  "item_text": "Permit-to-Work system compliance checked",                               "is_required": True},
                {"section_name": "KPIs",                 "item_no": 4,  "item_text": "KPI dashboard reviewed (incident rate, near-miss, compliance %)",        "is_required": True},
                {"section_name": "CAPA",                 "item_no": 5,  "item_text": "CAPA overdue items actioned",                                            "is_required": True},
                {"section_name": "Emergency",            "item_no": 6,  "item_text": "Emergency contacts and escalation list current",                         "is_required": True},
            ],
        },
        {
            "checklist_type": "manager_weekly_audit",
            "display_name":   "Manager Weekly Site Management Audit",
            "submitter_roles": ["Manager", "HSE Manager", "Admin", "Director"],
            "validator_roles": admin_validator,
            "ui":  {"form_title": "Weekly Site Management Audit", "short_label": "Weekly Audit", "version_tag": "v1.0"},
            "sla": {"draft_submission_sla_hours": 168, "validation_sla_hours": 48},
            "items": [
                {"section_name": "Training",             "item_no": 1,  "item_text": "HSE training records up to date for all staff",                          "is_required": True},
                {"section_name": "Legal",                "item_no": 2,  "item_text": "Legal compliance documents valid (licenses, certifications)",            "is_required": True},
                {"section_name": "Risk Assessment",      "item_no": 3,  "item_text": "Risk assessment reviews completed for active tasks",                     "is_required": True},
                {"section_name": "Findings",             "item_no": 4,  "item_text": "Inspection findings actioned within SLA",                                "is_required": True},
                {"section_name": "Records",              "item_no": 5,  "item_text": "Toolbox Talk records maintained",                                        "is_required": True},
                {"section_name": "Trends",               "item_no": 6,  "item_text": "Near-miss trend analysis done",                                          "is_required": True},
                {"section_name": "Walkthrough",          "item_no": 7,  "item_text": "Safety walkthrough conducted personally (enter date)",                   "is_required": True},
                {"section_name": "Contractors",          "item_no": 8,  "item_text": "Contractor HSE compliance verified",                                     "is_required": False},
                {"section_name": "Budget",               "item_no": 9,  "item_text": "Budget for HSE resources adequate",                                      "is_required": True},
                {"section_name": "Meetings",             "item_no": 10, "item_text": "HSE Meeting conducted with supervisors (attach minutes)",                "is_required": True},
            ],
        },
        {
            "checklist_type": "manager_monthly_compliance",
            "display_name":   "Manager Monthly Compliance Checklist",
            "submitter_roles": ["Manager", "HSE Manager", "Admin", "Director"],
            "validator_roles": admin_validator,
            "ui":  {"form_title": "Monthly Compliance Checklist", "short_label": "Monthly Compliance", "version_tag": "v1.0"},
            "sla": {"draft_submission_sla_hours": 720, "validation_sla_hours": 72},
            "items": [
                {"section_name": "Reporting",            "item_no": 1,  "item_text": "Monthly HSE performance report submitted",                               "is_required": True},
                {"section_name": "Audits",               "item_no": 2,  "item_text": "Audit findings from previous month closed (enter % closed)",            "is_required": True},
                {"section_name": "Regulatory",           "item_no": 3,  "item_text": "Regulatory/statutory returns filed",                                     "is_required": True},
                {"section_name": "Drills",               "item_no": 4,  "item_text": "Emergency drill conducted (enter date)",                                 "is_required": True},
                {"section_name": "Policy",               "item_no": 5,  "item_text": "HSE Policy reviewed and communicated",                                   "is_required": True},
                {"section_name": "Investigations",       "item_no": 6,  "item_text": "Incident investigation reports finalized",                               "is_required": True},
                {"section_name": "Feedback",             "item_no": 7,  "item_text": "Worker feedback on safety culture collected",                            "is_required": True},
            ],
        },
        {
            "checklist_type": "auditor_periodic_audit",
            "display_name":   "Auditor Periodic HSE Site Safety Audit",
            "submitter_roles": ["Auditor", "Admin", "HSE Manager"],
            "validator_roles": admin_validator,
            "ui":  {"form_title": "Periodic HSE Site Safety Audit", "short_label": "HSE Audit", "version_tag": "v1.0"},
            "sla": {"draft_submission_sla_hours": 24, "validation_sla_hours": 48},
            "items": [
                {"section_name": "Permits",              "item_no": 1,  "item_text": "Active permits physically displayed at all active work locations",         "is_required": True},
                {"section_name": "Emergency",            "item_no": 2,  "item_text": "Emergency exit routes completely clear and assembly points unobstructed", "is_required": True},
                {"section_name": "PPE",                  "item_no": 3,  "item_text": "All personnel (including contractors and visitors) wearing correct PPE", "is_required": True},
                {"section_name": "Hazardous Storage",    "item_no": 4,  "item_text": "Chemicals and hazardous materials stored in secondary containment",       "is_required": True},
                {"section_name": "Heavy Machinery",      "item_no": 5,  "item_text": "Crane, hoisting equipment, and pressure vessels have valid test certificates", "is_required": True},
                {"section_name": "Medical",              "item_no": 6,  "item_text": "Site medical room / First aid boxes stocked, emergency vehicle path clear", "is_required": True},
                {"section_name": "Access Control",       "item_no": 7,  "item_text": "Walkways, scaffolding stairs, and exit doors are free of clutter/trip hazards", "is_required": True},
                {"section_name": "Electrical",           "item_no": 8,  "item_text": "Electrical distribution boards locked, cables safely routed and tagged", "is_required": True},
                {"section_name": "Height Work",          "item_no": 9,  "item_text": "Scaffolding green-tagged and safety harnesses tied off to anchors",      "is_required": True},
                {"section_name": "Contractors",          "item_no": 10, "item_text": "Contractor compliance records (toolbox, induction) verified on site",     "is_required": True},
            ],
        },
    ]
