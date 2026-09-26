"""WF-06 · Fatigue declaration and index (AI-ISMS class C7).

    worker      POST /fatigue/declare        shift hours, consecutive days, nights
    worker      GET  /fatigue/index          live index before requesting a permit
    worker      GET  /fatigue/mine
    supervisor  GET  /fatigue/team           live flag rate
    supervisor  POST /fatigue/{id}/acknowledge   10-14 band
    supervisor  POST /fatigue/{id}/sign-off      15-19 band, mandatory note
    manager     POST /fatigue/{id}/exception     >=20, Safety Manager only
    auditor     GET  /fatigue/audit-list

Non-medical proxies only. The spec is explicit that this must never become a
medical or biometric record, so nothing here stores a health attribute.
"""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.controllers.workflow_common import (
    AUDITOR_ROLES,
    MANAGER_ROLES,
    SUPERVISOR_ROLES,
    employee_id_for,
    require_role,
)
from app.core.dependencies import CurrentUser, get_current_user
from app.models.fatigue import FatigueDeclaration
from app.schemas.competence import (
    FatigueAck,
    FatigueDeclare,
    FatigueException,
    FatigueIndexResponse,
    FatigueResponse,
)
from app.services.hse_formulae import fatigue_index

router = APIRouter(prefix="/fatigue", tags=["Fatigue & Human Readiness"])


def _to_response(row: FatigueDeclaration) -> FatigueResponse:
    return FatigueResponse(
        id=row.id,
        employee_id=row.employee_id,
        declared_at=row.declared_at,
        shift_hours=float(row.shift_hours or 0),
        consecutive_days=int(row.consecutive_days or 0),
        night_shifts_7d=int(row.night_shifts_7d or 0),
        task_intensity=row.task_intensity,
        fatigue_index=float(row.fatigue_index or 0),
        band=row.band,
        supervisor_ack_at=row.supervisor_ack_at,
        supervisor_signoff_at=row.supervisor_signoff_at,
        exception_at=row.exception_at,
        exception_reason=row.exception_reason,
    )


@router.get("/index", response_model=FatigueIndexResponse)
def live_index(
    shift_hours: float = Query(..., ge=0, le=24),
    consecutive_days: int = Query(0, ge=0, le=60),
    night_shifts_7d: int = Query(0, ge=0, le=7),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Live index shown before a permit request — nothing is stored."""
    r = fatigue_index(shift_hours, consecutive_days, night_shifts_7d)
    return FatigueIndexResponse(
        fatigue_index=r.fatigue_index,
        band=r.band,
        shift_component=r.shift_component,
        consecutive_component=r.consecutive_component,
        night_component=r.night_component,
        requires_supervisor_ack=r.requires_supervisor_ack,
        requires_signoff=r.requires_signoff,
        is_hard_block=r.is_hard_block,
        explanation=r.explanation,
    )


@router.post("/declare", response_model=FatigueResponse, status_code=201)
def declare(
    payload: FatigueDeclare,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    emp_id = payload.employee_id or employee_id_for(db, current_user.user_id)
    if not emp_id:
        raise HTTPException(status_code=400, detail="No employee record linked to this user")
    if payload.employee_id and payload.employee_id != employee_id_for(db, current_user.user_id):
        require_role(
            current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES,
            "declare fatigue on behalf of another worker",
        )

    r = fatigue_index(payload.shift_hours, payload.consecutive_days, payload.night_shifts_7d)
    now = datetime.now()

    row = FatigueDeclaration(
        organisation_id=current_user.org_id,
        employee_id=emp_id,
        declared_at=now,
        shift_hours=payload.shift_hours,
        consecutive_days=payload.consecutive_days,
        night_shifts_7d=payload.night_shifts_7d,
        task_intensity=payload.task_intensity,
        fatigue_index=r.fatigue_index,
        band=r.band,
        source_system="mobile",
        last_verified_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_response(row)


@router.get("/mine", response_model=List[FatigueResponse])
def my_declarations(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    emp_id = employee_id_for(db, current_user.user_id)
    rows = (
        db.query(FatigueDeclaration)
        .filter(FatigueDeclaration.employee_id == emp_id)
        .order_by(FatigueDeclaration.id.desc())
        .limit(30)
        .all()
    )
    return [_to_response(r) for r in rows]


@router.get("/team", response_model=List[FatigueResponse])
def team_fatigue(
    days: int = Query(1, ge=1, le=30),
    band: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Live flag rate for the supervisor's gate override console."""
    require_role(
        current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES | AUDITOR_ROLES,
        "view team fatigue",
    )
    q = (
        db.query(FatigueDeclaration)
        .filter(FatigueDeclaration.organisation_id == current_user.org_id)
        .filter(FatigueDeclaration.declared_at >= datetime.now() - timedelta(days=days))
    )
    if band:
        q = q.filter(FatigueDeclaration.band == band)
    return [_to_response(r) for r in q.order_by(FatigueDeclaration.fatigue_index.desc()).all()]


@router.post("/{declaration_id}/acknowledge", response_model=FatigueResponse)
def acknowledge(
    declaration_id: int,
    payload: FatigueAck,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """10-14 amber band — the supervisor acknowledges before work proceeds."""
    require_role(current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES, "acknowledge a fatigue flag")
    row = db.query(FatigueDeclaration).filter(FatigueDeclaration.id == declaration_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Fatigue declaration not found")

    row.supervisor_ack_by = employee_id_for(db, current_user.user_id)
    row.supervisor_ack_at = datetime.now()
    if payload.note:
        row.signoff_note = payload.note
    db.commit()
    db.refresh(row)
    return _to_response(row)


@router.post("/{declaration_id}/sign-off", response_model=FatigueResponse)
def sign_off(
    declaration_id: int,
    payload: FatigueAck,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """15-19 band — sign-off with a mandatory note before a high-risk permit."""
    require_role(current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES, "sign off a fatigue flag")
    if not payload.note:
        raise HTTPException(status_code=400, detail="A written note is mandatory for sign-off")

    row = db.query(FatigueDeclaration).filter(FatigueDeclaration.id == declaration_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Fatigue declaration not found")

    row.supervisor_signoff_by = employee_id_for(db, current_user.user_id)
    row.supervisor_signoff_at = datetime.now()
    row.signoff_note = payload.note
    db.commit()
    db.refresh(row)
    return _to_response(row)


@router.post("/{declaration_id}/exception", response_model=FatigueResponse)
def safety_manager_exception(
    declaration_id: int,
    payload: FatigueException,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """The only route past a >=20 hard block.

    "Only role able to authorise F >= 20, with rationale." A supervisor cannot
    do this, and the AI can never do it.
    """
    require_role(current_user.role, MANAGER_ROLES, "authorise a fatigue exception")
    row = db.query(FatigueDeclaration).filter(FatigueDeclaration.id == declaration_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Fatigue declaration not found")

    row.exception_by = employee_id_for(db, current_user.user_id)
    row.exception_at = datetime.now()
    row.exception_reason = payload.reason
    row.override_history = (row.override_history or []) + [
        {
            "at": datetime.now().isoformat(),
            "by_user_id": current_user.user_id,
            "role": current_user.role,
            "reason": payload.reason,
            "fatigue_index": float(row.fatigue_index or 0),
        }
    ]
    db.commit()
    db.refresh(row)
    return _to_response(row)


@router.get("/audit-list", response_model=List[FatigueResponse])
def audit_list(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Every declaration that needed an acknowledgement, sign-off or exception."""
    require_role(current_user.role, AUDITOR_ROLES | MANAGER_ROLES, "audit fatigue declarations")
    rows = (
        db.query(FatigueDeclaration)
        .filter(FatigueDeclaration.organisation_id == current_user.org_id)
        .filter(FatigueDeclaration.declared_at >= datetime.now() - timedelta(days=days))
        .filter(FatigueDeclaration.band != "acceptable")
        .order_by(FatigueDeclaration.fatigue_index.desc())
        .all()
    )
    return [_to_response(r) for r in rows]
