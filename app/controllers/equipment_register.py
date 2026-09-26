from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.controllers.workflow_common import require_role, ALL_ELEVATED_ROLES
from app.models.equipment import Equipment

router = APIRouter(prefix="/equipment-register", tags=["Equipment Register"])


def _org_filter(query, model, org_id):
    if org_id is not None:
        return query.filter(model.organisation_id == org_id)
    return query


def _row_dict(r: Equipment, today: date) -> dict:
    return {
        "id": r.id,
        "equipment_code": r.equipment_code,
        "equipment_name": r.equipment_name,
        "equipment_type": r.equipment_type,
        "location_station": r.location_station,
        "installation_date": r.installation_date.isoformat() if r.installation_date else None,
        "pm_interval_days": r.pm_interval_days,
        "last_pm_date": r.last_pm_date.isoformat() if r.last_pm_date else None,
        "next_pm_due": r.next_pm_due.isoformat() if r.next_pm_due else None,
        "pm_overdue": bool(r.next_pm_due and r.next_pm_due < today),
        "operating_hours_ytd": r.operating_hours_ytd,
        "last_failure_date": r.last_failure_date.isoformat() if r.last_failure_date else None,
        "mtbf_hours_estimated": float(r.mtbf_hours_estimated) if r.mtbf_hours_estimated is not None else None,
        "safety_critical_sce": bool(r.safety_critical_sce),
        "status": r.status,
    }


class EquipmentCreate(BaseModel):
    equipment_code: str
    equipment_name: str
    equipment_type: Optional[str] = None
    location_station: Optional[str] = None
    installation_date: Optional[date] = None
    pm_interval_days: Optional[int] = None
    last_pm_date: Optional[date] = None
    next_pm_due: Optional[date] = None
    operating_hours_ytd: Optional[int] = None
    last_failure_date: Optional[date] = None
    mtbf_hours_estimated: Optional[float] = None
    safety_critical_sce: bool = False
    status: Optional[str] = None


class EquipmentUpdate(EquipmentCreate):
    pass


@router.get("/summary")
def get_equipment_summary(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Module 4 (Assets & Operations) — the client's own asset register
    (Assets_Sample_Data.xlsx, Assets_Register sheet) unlocks 3 of the 4
    Module 4 KPIs the spec previously flagged not computable for lack of any
    CMMS/asset register data:

        MTBF (fleet avg)  = AVERAGE(MTBF_Hours_Estimated) across the register
        PM Compliance %   = equipment not overdue on Next_PM_Due / total x 100
                             (PROXY: the register has no work-order log, so
                             this reads "not yet overdue" rather than "WO
                             completed on time" — treat as indicative only)
        SCE Overdue Count = safety-critical equipment (Safety_Critical_SCE)
                             past its own Next_PM_Due

    Scheduled Inspection Compliance % remains not computable — it needs a
    dedicated inspection work-order log (WO_Type = Scheduled Inspection),
    which this register doesn't carry.
    """
    org_id = current_user.org_id
    today = date.today()

    rows = _org_filter(db.query(Equipment), Equipment, org_id).all()
    total_equipment = len(rows)

    status_counts: dict[str, int] = {}
    for r in rows:
        key = r.status or "Unknown"
        status_counts[key] = status_counts.get(key, 0) + 1

    type_counts: dict[str, int] = {}
    for r in rows:
        key = r.equipment_type or "Unclassified"
        type_counts[key] = type_counts.get(key, 0) + 1
    equipment_by_type = [
        {"type": k, "count": v} for k, v in sorted(type_counts.items(), key=lambda kv: -kv[1])
    ]

    sce_rows = [r for r in rows if r.safety_critical_sce]
    sce_count = len(sce_rows)
    sce_overdue_count = sum(1 for r in sce_rows if r.next_pm_due and r.next_pm_due < today)

    mtbf_values = [float(r.mtbf_hours_estimated) for r in rows if r.mtbf_hours_estimated is not None]
    mtbf_avg = round(sum(mtbf_values) / len(mtbf_values), 1) if mtbf_values else None

    pm_due_rows = [r for r in rows if r.next_pm_due is not None]
    pm_not_overdue = sum(1 for r in pm_due_rows if r.next_pm_due >= today)
    pm_compliance_pct = round(pm_not_overdue / len(pm_due_rows) * 100, 1) if pm_due_rows else None

    return {
        "total_equipment": total_equipment,
        "status_counts": status_counts,
        "equipment_by_type": equipment_by_type,
        "sce_count": sce_count,
        "sce_overdue_count": sce_overdue_count,
        "mtbf_avg_hours": mtbf_avg,
        "pm_compliance_pct": pm_compliance_pct,
        "pm_compliance_note": "Proxy: equipment not yet past its Next PM Due date — no work-order completion log exists to confirm PM was actually performed on time.",
        "inspection_compliance_note": "Not computable — needs a dedicated inspection work-order log (Scheduled Inspection WO type), which this register doesn't include.",
    }


@router.get("/filter-options")
def get_equipment_filter_options(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    org_id = current_user.org_id
    types = [
        r[0] for r in
        _org_filter(db.query(Equipment.equipment_type), Equipment, org_id)
        .filter(Equipment.equipment_type.isnot(None))
        .distinct()
        .order_by(Equipment.equipment_type.asc())
        .all()
    ]
    statuses = [
        r[0] for r in
        _org_filter(db.query(Equipment.status), Equipment, org_id)
        .filter(Equipment.status.isnot(None))
        .distinct()
        .order_by(Equipment.status.asc())
        .all()
    ]
    return {"types": types, "statuses": statuses}


@router.get("")
def list_equipment(
    page: int = Query(1, ge=1),
    pageSize: int = Query(25, ge=1, le=200),
    status: Optional[str] = Query(None),
    equipment_type: Optional[str] = Query(None),
    sce: Optional[str] = Query(None, description="'Yes' or 'No' to filter safety-critical equipment"),
    q: Optional[str] = Query(None, description="Matches equipment code, name, or location"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    org_id = current_user.org_id
    today = date.today()

    base = _org_filter(db.query(Equipment), Equipment, org_id)
    if status and status != "All Status":
        base = base.filter(Equipment.status == status)
    if equipment_type and equipment_type != "All Types":
        base = base.filter(Equipment.equipment_type == equipment_type)
    if sce == "Yes":
        base = base.filter(Equipment.safety_critical_sce == 1)
    elif sce == "No":
        base = base.filter(Equipment.safety_critical_sce == 0)
    if q:
        like = f"%{q}%"
        base = base.filter(or_(
            Equipment.equipment_code.ilike(like),
            Equipment.equipment_name.ilike(like),
            Equipment.location_station.ilike(like),
        ))

    total = base.count()
    rows = (
        base.order_by(Equipment.equipment_code.asc())
        .offset((page - 1) * pageSize)
        .limit(pageSize)
        .all()
    )

    data = [_row_dict(r, today) for r in rows]

    return {
        "data": data,
        "total": total,
        "page": page,
        "pageSize": pageSize,
        "totalPages": (total + pageSize - 1) // pageSize if total else 0,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_equipment(
    payload: EquipmentCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, ALL_ELEVATED_ROLES, "create equipment records")
    row = Equipment(organisation_id=current_user.org_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return _row_dict(row, date.today())


@router.put("/{equipment_id}")
def update_equipment(
    equipment_id: int,
    payload: EquipmentUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, ALL_ELEVATED_ROLES, "update equipment records")
    row = _org_filter(
        db.query(Equipment).filter(Equipment.id == equipment_id), Equipment, current_user.org_id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Equipment not found")
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _row_dict(row, date.today())


@router.delete("/{equipment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_equipment(
    equipment_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, ALL_ELEVATED_ROLES, "delete equipment records")
    row = _org_filter(
        db.query(Equipment).filter(Equipment.id == equipment_id), Equipment, current_user.org_id
    ).first()
    if row:
        db.delete(row)
        db.commit()
