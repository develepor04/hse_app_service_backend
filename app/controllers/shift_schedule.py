from typing import List, Dict
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.models.shift_schedule import ShiftSchedule
from app.models.working_station import WorkingStation
from app.models.site import Site
from app.services.shift_schedule import ShiftScheduleService
from app.schemas.shift_schedule import ShiftScheduleCreate, ShiftScheduleUpdate, ShiftScheduleResponse

router = APIRouter(prefix="/shift-schedules", tags=["Shift Schedules"])


def _svc(db: Session = Depends(get_db)) -> ShiftScheduleService:
    return ShiftScheduleService(db)


@router.get("/patterns")
def get_shift_patterns(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)) -> List[Dict]:
    """Distinct shift patterns (Days/Nights/etc.) derived from real shift_schedule
    rows — the sites they run at and how many employees are currently on each,
    instead of the previous hardcoded Day/Afternoon/Night stub."""
    org_id = current_user.org_id

    q = db.query(
        ShiftSchedule.shift_type,
        func.min(ShiftSchedule.shift_start).label("start_time"),
        func.min(ShiftSchedule.shift_end).label("end_time"),
        func.count(func.distinct(ShiftSchedule.employee_id)).label("active_employees"),
    )
    if org_id is not None:
        q = q.filter(ShiftSchedule.organisation_id == org_id)
    q = q.filter(ShiftSchedule.shift_type.isnot(None)).group_by(ShiftSchedule.shift_type)
    rows = q.all()

    site_q = (
        db.query(ShiftSchedule.shift_type, Site.site_name)
        .join(WorkingStation, ShiftSchedule.station_id == WorkingStation.id)
        .join(Site, WorkingStation.site_id == Site.id)
        .filter(ShiftSchedule.shift_type.isnot(None))
    )
    if org_id is not None:
        site_q = site_q.filter(ShiftSchedule.organisation_id == org_id)
    sites_by_type: Dict[str, set] = {}
    for shift_type, site_name in site_q.distinct().all():
        sites_by_type.setdefault(shift_type, set()).add(site_name)

    return [
        {
            "shift_id": (row.shift_type or "").lower().replace(" ", "_"),
            "shift_name": row.shift_type,
            "start_time": str(row.start_time)[:5] if row.start_time else None,
            "end_time": str(row.end_time)[:5] if row.end_time else None,
            "sites": ", ".join(sorted(sites_by_type.get(row.shift_type, []))),
            "active_employees": row.active_employees,
        }
        for row in rows
    ]


@router.get("/", response_model=List[ShiftScheduleResponse])
def list_shift_schedules(skip: int = 0, limit: int = Query(100, le=1000), svc: ShiftScheduleService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.list(skip=skip, limit=limit, org_id=current_user.org_id)


@router.get("/{id}", response_model=ShiftScheduleResponse)
def get_shift_schedule(id: int, svc: ShiftScheduleService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.get(id, org_id=current_user.org_id)


@router.post("/", response_model=ShiftScheduleResponse, status_code=status.HTTP_201_CREATED)
def create_shift_schedule(payload: ShiftScheduleCreate, svc: ShiftScheduleService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.create(payload, org_id=current_user.org_id)


@router.put("/{id}", response_model=ShiftScheduleResponse)
def update_shift_schedule(id: int, payload: ShiftScheduleUpdate, svc: ShiftScheduleService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.update(id, payload, org_id=current_user.org_id)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shift_schedule(id: int, svc: ShiftScheduleService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    svc.delete(id, org_id=current_user.org_id)
