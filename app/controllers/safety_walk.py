from typing import List, Dict, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.services.safety_walk import SafetyWalkService
from app.schemas.safety_walk import SafetyWalkCreate, SafetyWalkUpdate, SafetyWalkResponse
from app.models.safety_walk import SafetyWalk
from app.models.working_station import WorkingStation
from app.models.employee import Employee
from app.utils.tenant import org_scoped_join

router = APIRouter(prefix="/safety-walks", tags=["Safety Walks"])


def _svc(db: Session = Depends(get_db)) -> SafetyWalkService:
    return SafetyWalkService(db)


def _org_filter(query, model, org_id):
    if org_id is not None:
        return query.filter(model.organisation_id == org_id)
    return query


@router.get("/", response_model=List[SafetyWalkResponse])
def list_safety_walks(skip: int = 0, limit: int = Query(100, le=1000), svc: SafetyWalkService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.list(skip=skip, limit=limit, org_id=current_user.org_id)


# ── Dedicated Site Inspection page (Workforce — Site Inspection Metrics,
# HSEIQ_Full_KPI_with_SampleData.xlsx / Workforce_SiteWalks) ──────────────────
#
# The client's own note on that sheet: this is real general site-inspection
# data, presented as context — it does NOT compute the spec's Module 3
# "Leadership Safety Walk Compliance %" KPI, which would need a scheduled-
# walks baseline this data doesn't carry. So this summary sticks to what the
# sheet itself reports (counts, averages, follow-up rate, type breakdown)
# rather than inventing a compliance-against-schedule figure with no data
# behind it.
@router.get("/summary")
def get_safety_walk_summary(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    org_id = current_user.org_id
    rows = _org_filter(db.query(SafetyWalk), SafetyWalk, org_id).all()
    total = len(rows)

    def _avg(values):
        vals = [v for v in values if v is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    avg_compliance = _avg(r.compliance_rating for r in rows)
    avg_housekeeping = _avg(r.housekeeping_rating for r in rows)
    critical_count = sum(1 for r in rows if (r.critical_issues or 0) > 0)
    follow_up_count = sum(1 for r in rows if (r.follow_up_required or "").strip().lower() == "yes")
    follow_up_rate_pct = round(follow_up_count / total * 100, 1) if total else None
    total_issues_found = sum(r.issues_found or 0 for r in rows)

    by_type: Dict[str, Dict[str, float]] = {}
    for r in rows:
        key = r.inspection_type or "Unclassified"
        bucket = by_type.setdefault(key, {"count": 0, "rating_sum": 0.0, "rating_n": 0})
        bucket["count"] += 1
        if r.compliance_rating is not None:
            bucket["rating_sum"] += r.compliance_rating
            bucket["rating_n"] += 1
    breakdown_by_type = [
        {
            "type": key,
            "count": b["count"],
            "avg_compliance_rating": round(b["rating_sum"] / b["rating_n"], 2) if b["rating_n"] else None,
        }
        for key, b in sorted(by_type.items(), key=lambda kv: -kv[1]["count"])
    ]

    return {
        "total_inspections": total,
        "avg_compliance_rating": avg_compliance,
        "avg_housekeeping_rating": avg_housekeeping,
        "inspections_with_critical_issue": critical_count,
        "inspections_requiring_follow_up": follow_up_count,
        "follow_up_rate_pct": follow_up_rate_pct,
        "total_issues_found": total_issues_found,
        "breakdown_by_type": breakdown_by_type,
    }


@router.get("/filter-options")
def get_safety_walk_filter_options(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    org_id = current_user.org_id
    types = [
        r[0] for r in
        _org_filter(db.query(SafetyWalk.inspection_type), SafetyWalk, org_id)
        .filter(SafetyWalk.inspection_type.isnot(None))
        .distinct()
        .order_by(SafetyWalk.inspection_type.asc())
        .all()
    ]
    return {"types": types}


PAGE_SIZE_DEFAULT = 25


@router.get("/register")
def list_safety_walk_register(
    page: int = Query(1, ge=1),
    pageSize: int = Query(PAGE_SIZE_DEFAULT, ge=1, le=200),
    inspection_type: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Matches inspection type, location or inspector"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    org_id = current_user.org_id
    base = (
        _org_filter(db.query(SafetyWalk, WorkingStation, Employee), SafetyWalk, org_id)
        .outerjoin(WorkingStation, org_scoped_join(SafetyWalk.location_station_id == WorkingStation.id, WorkingStation.organisation_id, org_id))
        .outerjoin(Employee, org_scoped_join(SafetyWalk.inspector_id == Employee.id, Employee.organisation_id, org_id))
    )
    if inspection_type and inspection_type != "All Types":
        base = base.filter(SafetyWalk.inspection_type == inspection_type)
    if q:
        like = f"%{q}%"
        base = base.filter(or_(
            SafetyWalk.inspection_type.ilike(like),
            WorkingStation.station_name.ilike(like),
            Employee.full_name.ilike(like),
        ))

    total = base.count()
    rows = (
        base.order_by(
            case((SafetyWalk.inspection_date_time.is_(None), 1), else_=0),
            SafetyWalk.inspection_date_time.desc(),
            SafetyWalk.id.desc(),
        )
        .offset((page - 1) * pageSize)
        .limit(pageSize)
        .all()
    )

    data = [
        {
            "id": sw.id,
            "reference": f"DSW-{sw.id:05d}",
            "inspection_date_time": sw.inspection_date_time.isoformat() if sw.inspection_date_time else None,
            "location": ws.station_name if ws else (f"Station {sw.location_station_id}" if sw.location_station_id else "Unknown"),
            "inspector": emp.full_name if emp else "Unknown",
            "inspection_type": sw.inspection_type,
            "issues_found": sw.issues_found or 0,
            "critical_issues": sw.critical_issues or 0,
            "housekeeping_rating": sw.housekeeping_rating,
            "compliance_rating": sw.compliance_rating,
            "follow_up_required": (sw.follow_up_required or "").strip().lower() == "yes",
            "priority": "Critical" if (sw.critical_issues or 0) > 0 else ("High" if (sw.issues_found or 0) > 2 else "Medium"),
        }
        for sw, ws, emp in rows
    ]

    return {
        "data": data,
        "total": total,
        "page": page,
        "pageSize": pageSize,
        "totalPages": (total + pageSize - 1) // pageSize if total else 0,
    }


@router.get("/{id}", response_model=SafetyWalkResponse)
def get_safety_walk(id: int, svc: SafetyWalkService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.get(id, org_id=current_user.org_id)


@router.post("/", response_model=SafetyWalkResponse, status_code=status.HTTP_201_CREATED)
def create_safety_walk(payload: SafetyWalkCreate, svc: SafetyWalkService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.create(payload, org_id=current_user.org_id)


@router.put("/{id}", response_model=SafetyWalkResponse)
def update_safety_walk(id: int, payload: SafetyWalkUpdate, svc: SafetyWalkService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.update(id, payload, org_id=current_user.org_id)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_safety_walk(id: int, svc: SafetyWalkService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    svc.delete(id, org_id=current_user.org_id)
