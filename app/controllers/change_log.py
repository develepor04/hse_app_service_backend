"""MOC-Lite · Change & Drift Log, plus the two event feeds WF-07 reads.

    manager     GET/POST /change-log                procedure, equipment, staffing,
                                                    temporary arrangements
    manager     POST     /change-log/{id}/review
    supervisor  POST     /change-log/toolbox        supervisor interaction (org health)
    system      POST     /change-log/work-event     permit bypass / late closure

From the Safety Manager column: "Change & Drift Log — procedure updates,
equipment mods, staffing changes, temporary arrangements. MOC-Lite risk-spike
input" (AI-ISMS class C8).

The two event feeds are here rather than in sps.py because they are *captured*
by people, whereas everything in sps.py is *derived* by the server.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.controllers.workflow_common import (
    ALL_READ_ROLES,
    MANAGER_ROLES,
    SUPERVISOR_ROLES,
    employee_id_for,
    require_role,
)
from app.core.dependencies import CurrentUser, get_current_user
from app.models.sps import ChangeEvent, SupervisorInteraction, WorkExecutionEvent

router = APIRouter(prefix="/change-log", tags=["Change & Drift"])

CHANGE_TYPES = {"procedure_update", "equipment_mod", "staffing_change", "temporary_arrangement"}

# How much each change type spikes risk while it is in force. Temporary
# arrangements score highest because they are the ones that quietly become
# permanent without ever being re-assessed.
RISK_SPIKE = {
    "temporary_arrangement": 30.0,
    "equipment_mod": 25.0,
    "staffing_change": 20.0,
    "procedure_update": 15.0,
}


class ChangeCreate(BaseModel):
    change_type: str = Field(..., pattern="^(procedure_update|equipment_mod|staffing_change|temporary_arrangement)$")
    title: str = Field(..., min_length=1)
    description: Optional[str] = None
    site_id: Optional[int] = None
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None


class ChangeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    change_type: str
    title: str
    description: Optional[str] = None
    site_id: Optional[int] = None
    risk_spike_score: Optional[float] = None
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    status: str
    reviewed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class ChangeReview(BaseModel):
    status: str = Field(..., pattern="^(open|reviewed|closed)$")
    notes: Optional[str] = None


class ToolboxLog(BaseModel):
    employee_id: Optional[int] = None
    interaction_type: str = Field("toolbox_talk", pattern="^(toolbox_talk|safety_walk|coaching|briefing)$")
    detail: Optional[str] = None


class WorkEventLog(BaseModel):
    event_type: str = Field(..., pattern="^(permit_bypass|late_closure|poor_closure|repeat_breach|under_permit)$")
    permit_id: Optional[int] = None
    employee_id: Optional[int] = None
    site_id: Optional[int] = None
    detail: Optional[str] = None


@router.get("", response_model=List[ChangeResponse])
@router.get("/", response_model=List[ChangeResponse])
def list_changes(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, ALL_READ_ROLES, "view the change log")
    q = db.query(ChangeEvent).filter(ChangeEvent.organisation_id == current_user.org_id)
    if status:
        q = q.filter(ChangeEvent.status == status)
    rows = q.order_by(ChangeEvent.id.desc()).limit(100).all()
    return [
        ChangeResponse(
            id=r.id, change_type=r.change_type, title=r.title, description=r.description,
            site_id=r.site_id,
            risk_spike_score=float(r.risk_spike_score) if r.risk_spike_score is not None else None,
            effective_from=str(r.effective_from) if r.effective_from else None,
            effective_to=str(r.effective_to) if r.effective_to else None,
            status=r.status, reviewed_at=r.reviewed_at, created_at=r.created_at,
        )
        for r in rows
    ]


@router.post("", response_model=ChangeResponse, status_code=201)
@router.post("/", response_model=ChangeResponse, status_code=201)
def raise_change(
    payload: ChangeCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES, "raise a change record")

    row = ChangeEvent(
        organisation_id=current_user.org_id,
        site_id=payload.site_id,
        change_type=payload.change_type,
        title=payload.title,
        description=payload.description,
        risk_spike_score=RISK_SPIKE.get(payload.change_type, 15.0),
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        raised_by=employee_id_for(db, current_user.user_id),
        status="open",
        source_system="mobile",
        last_verified_at=datetime.now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ChangeResponse(
        id=row.id, change_type=row.change_type, title=row.title, description=row.description,
        site_id=row.site_id, risk_spike_score=float(row.risk_spike_score or 0),
        effective_from=str(row.effective_from) if row.effective_from else None,
        effective_to=str(row.effective_to) if row.effective_to else None,
        status=row.status, reviewed_at=row.reviewed_at, created_at=row.created_at,
    )


@router.post("/{change_id}/review", response_model=ChangeResponse)
def review_change(
    change_id: int,
    payload: ChangeReview,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, MANAGER_ROLES, "review a change record")
    row = (
        db.query(ChangeEvent)
        .filter(ChangeEvent.id == change_id)
        .filter(ChangeEvent.organisation_id == current_user.org_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Change record not found")

    row.status = payload.status
    row.reviewed_by = employee_id_for(db, current_user.user_id)
    row.reviewed_at = datetime.now()
    row.last_reviewed_at = datetime.now()
    if payload.notes:
        row.description = f"{row.description or ''}\n\n[review] {payload.notes}".strip()
    db.commit()
    db.refresh(row)
    return ChangeResponse(
        id=row.id, change_type=row.change_type, title=row.title, description=row.description,
        site_id=row.site_id, risk_spike_score=float(row.risk_spike_score or 0),
        effective_from=str(row.effective_from) if row.effective_from else None,
        effective_to=str(row.effective_to) if row.effective_to else None,
        status=row.status, reviewed_at=row.reviewed_at, created_at=row.created_at,
    )


@router.post("/toolbox", status_code=201)
def log_interaction(
    payload: ToolboxLog,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Toolbox talk / safety walk / coaching — feeds the Org Health domain."""
    require_role(current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES, "log a supervisor interaction")
    row = SupervisorInteraction(
        organisation_id=current_user.org_id,
        supervisor_id=employee_id_for(db, current_user.user_id),
        employee_id=payload.employee_id,
        interaction_type=payload.interaction_type,
        detail=payload.detail,
        occurred_at=datetime.now(),
        source_system="mobile",
        last_verified_at=datetime.now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "interaction_type": row.interaction_type}


@router.post("/work-event", status_code=201)
def log_work_event(
    payload: WorkEventLog,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Permit bypass, late or poor closure — feeds the Work Discipline domain."""
    require_role(current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES, "log a work execution event")
    row = WorkExecutionEvent(
        organisation_id=current_user.org_id,
        site_id=payload.site_id,
        employee_id=payload.employee_id,
        permit_id=payload.permit_id,
        event_type=payload.event_type,
        detail=payload.detail,
        occurred_at=datetime.now(),
        source_system="mobile",
        last_verified_at=datetime.now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "event_type": row.event_type}
