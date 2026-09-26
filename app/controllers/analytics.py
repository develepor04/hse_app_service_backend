import math
import re
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, or_, String
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.utils.tenant import org_scoped_join
from app.models.audit import Audit, AuditFinding
from app.models.capa_action import CapaAction
from app.models.employee import Employee
from app.models.hazard import Hazard
from app.models.hazard_category import HazardCategory
from app.models.incident import Incident
from app.models.near_miss import NearMiss
from app.models.permit_to_work import PermitToWork
from app.models.permit_type import PermitType
from app.models.policy import Policy
from app.models.safety_walk import SafetyWalk
from app.models.site import Site
from app.models.working_station import WorkingStation
from app.services.audit_readiness import compute_audit_readiness
from app.services.rating_labels import get_rating_labels, label_and_tone

router = APIRouter(prefix="/analytics", tags=["Analytics"])

MONTH_NAMES = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
RCA_COLORS = ["#4F8C2F", "#F5C116", "#F59E0B", "#2F3A4F", "#607D8B"]


def _org_filter(query, model, org_id):
    """Filter by org_id only. NULL organisation rows are not tenant data."""
    if org_id is not None:
        return query.filter(model.organisation_id == org_id)
    return query


_FAKE_INCIDENT_REF_RE = re.compile(r"\s*\b(for|addressing)\s+INC-?\d+\b\.?", re.IGNORECASE)


def _clean_capa_description(capa) -> str:
    """Seed/legacy CAPA descriptions embed a made-up "INC00018"-style number
    unrelated to the real incident_id — see DashboardPage.tsx / vendor.py's
    _capa_label for the same fix elsewhere. Strips it so it can't be mistaken
    for a real incident reference; prefixes the real one when known."""
    desc = (capa.description or capa.action_type or "CAPA action")
    desc = _FAKE_INCIDENT_REF_RE.sub("", desc).strip() or (capa.action_type or "CAPA action")
    ref = f"INC-{capa.incident_id:05d} " if getattr(capa, "incident_id", None) else ""
    return f"{ref}{desc}"


@router.get("/violations-summary")
def get_violations_summary(months: int = 10, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    today = date.today()
    org_id = current_user.org_id

    by_type_rows = (
        _org_filter(
            db.query(Incident.incident_type, func.count(Incident.id).label("cnt"))
            .filter(Incident.incident_type.isnot(None)),
            Incident, org_id,
        )
        .group_by(Incident.incident_type)
        .order_by(func.count(Incident.id).desc())
        .limit(7)
        .all()
    )
    by_type = [{"label": r.incident_type, "value": r.cnt} for r in by_type_rows]

    by_location_rows = (
        _org_filter(db.query(WorkingStation.station_name, func.count(Incident.id).label("cnt")), WorkingStation, org_id)
        .join(Incident, org_scoped_join(Incident.location_station_id == WorkingStation.id, Incident.organisation_id, org_id))
        .filter(Incident.organisation_id == org_id if org_id is not None else True)
        .group_by(WorkingStation.station_name)
        .order_by(func.count(Incident.id).desc())
        .limit(7)
        .all()
    )
    by_location = [{"label": r.station_name, "value": r.cnt} for r in by_location_rows]

    by_root_cause_rows = (
        _org_filter(
            db.query(Incident.root_cause_category, func.count(Incident.id).label("cnt"))
            .filter(Incident.root_cause_category.isnot(None)),
            Incident, org_id,
        )
        .group_by(Incident.root_cause_category)
        .order_by(func.count(Incident.id).desc())
        .limit(5)
        .all()
    )
    by_root_cause = [
        {"name": r.root_cause_category, "value": r.cnt, "color": RCA_COLORS[i % len(RCA_COLORS)]}
        for i, r in enumerate(by_root_cause_rows)
    ]

    # Investigation Status breakdown — Excel KPI spec (M1_Incidents_Events, supporting
    # breakdown): Completed / In Progress / Not Investigated, via COUNTIF Investigation_Status.
    INVESTIGATION_STATUS_COLORS = {
        "completed": "#16A34A",
        "closed": "#0F766E",
        "in progress": "#F59E0B",
        "acknowledged": "#3B82F6",
        "open": "#EF4444",
        "not investigated": "#9CA3AF",
    }
    investigation_status_rows = (
        _org_filter(
            db.query(Incident.investigation_status, func.count(Incident.id).label("cnt"))
            .filter(Incident.investigation_status.isnot(None)),
            Incident, org_id,
        )
        .group_by(Incident.investigation_status)
        .order_by(func.count(Incident.id).desc())
        .all()
    )
    investigation_status = [
        {
            "name": r.investigation_status,
            "value": r.cnt,
            "color": INVESTIGATION_STATUS_COLORS.get((r.investigation_status or "").lower(), "#94A3B8"),
        }
        for r in investigation_status_rows
    ]

    monthly_rows = (
        _org_filter(
            db.query(
                func.year(Incident.incident_date_time).label("yr"),
                func.month(Incident.incident_date_time).label("mo"),
                func.count(Incident.id).label("cnt"),
            ).filter(Incident.incident_date_time.isnot(None)),
            Incident, org_id,
        )
        .group_by("yr", "mo")
        .order_by("yr", "mo")
        .all()
    )
    monthly_trend = [
        {"month": MONTH_NAMES[int(r.mo) - 1], "value": r.cnt}
        for r in monthly_rows[-months:]
    ]

    nm_rows = (
        _org_filter(
            db.query(
                func.year(NearMiss.event_date_time).label("yr"),
                func.month(NearMiss.event_date_time).label("mo"),
                func.count(NearMiss.id).label("cnt"),
            ).filter(NearMiss.event_date_time.isnot(None)),
            NearMiss, org_id,
        )
        .group_by("yr", "mo")
        .order_by("yr", "mo")
        .all()
    )
    near_miss_monthly = [
        {"month": MONTH_NAMES[int(r.mo) - 1], "value": r.cnt}
        for r in nm_rows[-months:]
    ]

    downtime_rows = (
        _org_filter(
            db.query(Incident.incident_type, func.sum(Incident.days_away).label("total"))
            .filter(
                Incident.days_away.isnot(None),
                Incident.incident_type.isnot(None),
                # A near-miss has no actual injury/lost time by definition — a Near-miss
                # record carrying Days_Away is a data-entry error (see client's own Data
                # Quality Findings, e.g. INC00037) and shouldn't count toward downtime.
                func.lower(Incident.incident_type) != "near-miss",
            ),
            Incident, org_id,
        )
        .group_by(Incident.incident_type)
        .order_by(func.sum(Incident.days_away).desc())
        .limit(5)
        .all()
    )
    downtime_by_type = [
        {"label": r.incident_type, "value": float(r.total) if r.total else 0}
        for r in downtime_rows
    ]

    open_capa = (
        _org_filter(
            db.query(CapaAction).filter((CapaAction.status.is_(None)) | func.lower(CapaAction.status).notin_(["completed", "closed", "verified", "done"])),
            CapaAction, org_id,
        )
        .order_by(case((CapaAction.due_date.is_(None), 1), else_=0), CapaAction.due_date.asc())
        .limit(4)
        .all()
    )
    open_capa_items = [
        f"{_clean_capa_description(c)} (#{c.id})"
        for c in open_capa
    ]

    sev_rows = (
        _org_filter(
            db.query(
                func.year(Incident.incident_date_time).label("yr"),
                func.month(Incident.incident_date_time).label("mo"),
                func.lower(Incident.severity).label("sev"),
                func.count(Incident.id).label("cnt"),
            ).filter(Incident.incident_date_time.isnot(None), Incident.severity.isnot(None)),
            Incident, org_id,
        )
        .group_by("yr", "mo", "sev")
        .order_by("yr", "mo")
        .all()
    )
    months_map: dict = {}
    for r in sev_rows:
        key = f"{int(r.yr)}-{int(r.mo):02d}"
        label = MONTH_NAMES[int(r.mo) - 1]
        if key not in months_map:
            months_map[key] = {"label": label, "critical": 0, "high": 0, "medium": 0, "low": 0}
        bucket = _rca_priority(r.sev).lower()
        months_map[key][bucket] += r.cnt
    severity_mix = list(months_map.values())[-months:]

    # Injury cause (immediate_cause column — closest proxy to body-part/injury cause)
    injury_cat_rows = (
        _org_filter(
            db.query(Incident.immediate_cause, func.count(Incident.id).label("cnt"))
            .filter(Incident.immediate_cause.isnot(None)),
            Incident, org_id,
        )
        .group_by(Incident.immediate_cause)
        .order_by(func.count(Incident.id).desc())
        .limit(7)
        .all()
    )
    injury_category = [{"label": r.immediate_cause, "value": r.cnt} for r in injury_cat_rows]

    # Person involved — group by employment_type of the employee who reported
    person_rows = (
        db.query(Employee.employment_type, func.count(Incident.id).label("cnt"))
        .join(Incident, org_scoped_join(Incident.reported_by == Employee.id, Employee.organisation_id, org_id))
        .filter(
            Employee.employment_type.isnot(None),
            *([Incident.organisation_id == org_id] if org_id is not None else []),
        )
        .group_by(Employee.employment_type)
        .order_by(func.count(Incident.id).desc())
        .limit(6)
        .all()
    )
    person_involved = [{"label": r.employment_type, "value": r.cnt} for r in person_rows]

    # Injury type — root_cause column describes how the injury happened
    injury_type_rows = (
        _org_filter(
            db.query(Incident.root_cause, func.count(Incident.id).label("cnt"))
            .filter(Incident.root_cause.isnot(None)),
            Incident, org_id,
        )
        .group_by(Incident.root_cause)
        .order_by(func.count(Incident.id).desc())
        .limit(7)
        .all()
    )
    injury_type = [{"label": r.root_cause, "value": r.cnt} for r in injury_type_rows]

    # Key learnings — latest incident descriptions (first sentence, max 120 chars)
    learning_rows = (
        _org_filter(
            db.query(Incident.description)
            .filter(Incident.description.isnot(None)),
            Incident, org_id,
        )
        .order_by(Incident.id.desc())
        .limit(6)
        .all()
    )
    key_learnings = [
        (r.description.split(".")[0].strip()[:120] or r.description[:120])
        for r in learning_rows
        if r.description
    ]

    return {
        "by_type": by_type,
        "by_location": by_location,
        "by_root_cause": by_root_cause,
        "investigation_status": investigation_status,
        "monthly_trend": monthly_trend,
        "near_miss_monthly": near_miss_monthly,
        "downtime_by_type": downtime_by_type,
        "open_capa_items": open_capa_items,
        "severity_mix": severity_mix,
        "injury_category": injury_category,
        "person_involved": person_involved,
        "injury_type": injury_type,
        "key_learnings": key_learnings,
    }


@router.get("/permits-summary")
def get_permits_summary(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    org_id = current_user.org_id

    active_count = _org_filter(
        db.query(PermitToWork).filter(PermitToWork.status == "Active"),
        PermitToWork, org_id,
    ).count()

    total_workers = _org_filter(
        db.query(func.sum(PermitToWork.number_of_workers)).filter(PermitToWork.status == "Active"),
        PermitToWork, org_id,
    ).scalar() or 0

    by_type_rows = (
        db.query(PermitType.permit_type_name, PermitType.risk_level, func.count(PermitToWork.id).label("cnt"))
        .join(PermitToWork, PermitToWork.permit_type_id == PermitType.id)
        .filter(
            PermitToWork.status == "Active",
            *([PermitToWork.organisation_id == org_id, PermitType.organisation_id == org_id] if org_id is not None else []),
        )
        .group_by(PermitType.permit_type_name, PermitType.risk_level)
        .order_by(func.count(PermitToWork.id).desc())
        .limit(6)
        .all()
    )
    # "High Risk Work" = active permit count weighted by the permit type's own risk_level,
    # not a plain count — a "Cold Work" permit and a "Confined Space Entry" permit are not
    # equally risky even at the same volume.
    _RISK_WEIGHT = {"critical": 3.0, "high": 2.0, "medium": 1.0, "low": 0.5}
    weighted_scores = [
        r.cnt * _RISK_WEIGHT.get((r.risk_level or "").lower(), 1.0) for r in by_type_rows
    ]
    max_score = max(weighted_scores, default=1) or 1
    risk_work_data = [
        {"subject": r.permit_type_name, "A": round(score / max_score * 100)}
        for r, score in zip(by_type_rows, weighted_scores)
    ]

    # ── Permit Violations (same logic as /vendors/summary for data consistency) ──
    # Uses permits with deviation_reported = "Yes" — single source of truth
    viol_rows = (
        db.query(PermitToWork, WorkingStation)
        .outerjoin(WorkingStation, org_scoped_join(PermitToWork.location_station_id == WorkingStation.id, WorkingStation.organisation_id, org_id))
        .filter(
            PermitToWork.deviation_reported == "Yes",
            *([PermitToWork.organisation_id == org_id] if org_id is not None else []),
        )
        .order_by(PermitToWork.date_issued.desc())
        .limit(5)
        .all()
    )
    permit_violations = [
        {
            "text": f"PTW-{ptw.id:04d} — {ws.station_name if ws else 'Site'}: Deviation Reported",
            "time": ptw.date_issued.strftime("%d %b %Y") if ptw.date_issued else "N/A",
        }
        for ptw, ws in viol_rows
    ]

    active_rows = (
        db.query(PermitToWork, PermitType, WorkingStation, Employee)
        .outerjoin(PermitType, org_scoped_join(PermitToWork.permit_type_id == PermitType.id, PermitType.organisation_id, org_id))
        .outerjoin(WorkingStation, org_scoped_join(PermitToWork.location_station_id == WorkingStation.id, WorkingStation.organisation_id, org_id))
        .outerjoin(Employee, org_scoped_join(PermitToWork.issued_by == Employee.id, Employee.organisation_id, org_id))
        .filter(
            PermitToWork.status == "Active",
            *([PermitToWork.organisation_id == org_id] if org_id is not None else []),
        )
        .order_by(case((PermitToWork.validity_end.is_(None), 1), else_=0), PermitToWork.validity_end.asc())
        .limit(10)
        .all()
    )

    def fmt_expiry(end_dt) -> str:
        if not end_dt:
            return "N/A"
        return end_dt.strftime("%b %d, %H:%M") if hasattr(end_dt, "hour") else end_dt.strftime("%b %d, %Y")

    active_work_rows = [
        {
            "id": f"PTW-{ptw.id:04d}",
            "type": pt.permit_type_name if pt else "Unknown",
            "issued_by": emp.full_name if emp else "Unassigned",
            "location": ws.station_name if ws else (f"Station {ptw.location_station_id}" if ptw.location_station_id else "Unknown"),
            "status": ptw.status,
            "expiry": fmt_expiry(ptw.validity_end),
        }
        for ptw, pt, ws, emp in active_rows
    ]

    # Bar width reflects the permit's real requested duration (not an arbitrary
    # per-row index) — so the timeline actually represents the underlying data.
    def _permit_hours(ptw) -> float:
        if ptw.validity_start and ptw.validity_end:
            return max(0.0, (ptw.validity_end - ptw.validity_start).total_seconds() / 3600)
        return float(ptw.duration_requested_hours or 0)

    top5 = active_rows[:5]
    durations = [_permit_hours(ptw) for ptw, pt, ws, emp in top5]
    max_duration = max(durations) if durations else 1
    timeline_colors = ["#D64545", "#C14B4B", "#E8B441", "#42A5C6", "#5070C9"]
    expiry_timeline = [
        {
            "label": f"{row['id']} ({row['expiry']})",
            "left": 2,
            "width": round(max(15, durations[i] / max_duration * 90)) if max_duration else 15,
            "color": timeline_colors[i % len(timeline_colors)],
            "rightText": row["expiry"],
        }
        for i, row in enumerate(active_work_rows[:5])
    ]

    work_exposure_hours = int(
        _org_filter(
            db.query(func.sum(PermitToWork.duration_requested_hours * PermitToWork.number_of_workers))
            .filter(PermitToWork.status == "Active"),
            PermitToWork, org_id,
        ).scalar() or 0
    )

    total_permits = _org_filter(db.query(PermitToWork), PermitToWork, org_id).count()
    # Excel KPI spec (M4_Assets_Operations): PTW Compliance Rate = Closed / Total × 100
    # "Properly closed" = Status = "Closed"; Expired = non-compliant; Active = excluded from base (still open)
    closed_permits = _org_filter(
        db.query(PermitToWork).filter(PermitToWork.status == "Closed"),
        PermitToWork, org_id,
    ).count()
    permit_compliance_pct = round(closed_permits / total_permits * 100, 1) if total_permits else 0

    is_contractor = func.lower(Employee.employment_type).like("%contract%")
    contractor_q = db.query(Employee).filter(is_contractor)
    if org_id is not None:
        contractor_q = contractor_q.filter(Employee.organisation_id == org_id)
    contractor_employee_ids = [e.id for e in contractor_q.all()]

    contractor_permit_filter = or_(
        PermitToWork.issued_by.in_(contractor_employee_ids),
        PermitToWork.approved_by.in_(contractor_employee_ids),
    ) if contractor_employee_ids else None
    if contractor_permit_filter is not None:
        contractor_total = _org_filter(
            db.query(PermitToWork).filter(contractor_permit_filter), PermitToWork, org_id
        ).count()
        # Excel KPI spec (M4): PTW Compliance Rate = Closed / Total × 100
        contractor_compliant = _org_filter(
            db.query(PermitToWork).filter(
                contractor_permit_filter,
                PermitToWork.status == "Closed",
            ),
            PermitToWork, org_id,
        ).count()
    else:
        contractor_total = contractor_compliant = 0
    contractor_compliant_pct = round(contractor_compliant / contractor_total * 100) if contractor_total else 0
    contractor_non_compliant_pct = 100 - contractor_compliant_pct if contractor_total else 0

    deviation_rows = (
        db.query(PermitToWork, PermitType)
        .outerjoin(PermitType, org_scoped_join(PermitToWork.permit_type_id == PermitType.id, PermitType.organisation_id, org_id))
        .filter(
            PermitToWork.status == "Active",
            PermitToWork.deviation_reported == "Yes",
            *([PermitToWork.organisation_id == org_id] if org_id is not None else []),
        )
        .order_by(case((PermitToWork.validity_end.is_(None), 1), else_=0), PermitToWork.validity_end.asc())
        .limit(4)
        .all()
    )
    missing_controls = [
        f"{ptw.work_description or (pt.permit_type_name if pt else 'Work')} — Deviation Reported (PTW-{ptw.id:04d})"
        for ptw, pt in deviation_rows
    ]

    type_status_rows = (
        db.query(PermitType.permit_type_name, PermitToWork.status, func.count(PermitToWork.id))
        .join(PermitToWork, PermitToWork.permit_type_id == PermitType.id)
        .filter(*([PermitToWork.organisation_id == org_id, PermitType.organisation_id == org_id] if org_id is not None else []))
        .group_by(PermitType.permit_type_name, PermitToWork.status)
        .all()
    )
    by_type_status: Dict[str, Dict[str, int]] = {}
    for type_name, status_val, cnt in type_status_rows:
        by_type_status.setdefault(type_name, {})[status_val or "Unknown"] = cnt
    work_by_type = []
    for type_name, status_counts in sorted(by_type_status.items(), key=lambda kv: -sum(kv[1].values()))[:6]:
        total_for_type = sum(status_counts.values()) or 1
        work_by_type.append({
            "name": type_name,
            "active": round(status_counts.get("Active", 0) / total_for_type * 100),
            "closed": round(status_counts.get("Closed", 0) / total_for_type * 100),
            "expired": round(status_counts.get("Expired", 0) / total_for_type * 100),
        })

    return {
        "active_permits": active_count,
        "total_workers_on_site": int(total_workers),
        "risk_work_data": risk_work_data,
        "permit_violations": permit_violations,
        "active_work_rows": active_work_rows,
        "expiry_timeline": expiry_timeline,
        "work_exposure_hours": work_exposure_hours,
        "permit_compliance_pct": permit_compliance_pct,
        "missing_controls": missing_controls,
        "work_by_type": work_by_type,
        "contractor_compliant_pct": contractor_compliant_pct,
        "contractor_non_compliant_pct": contractor_non_compliant_pct,
    }


@router.get("/permits/all")
def get_all_permits(
    page: int = Query(1, ge=1),
    pageSize: int = Query(25, ge=1, le=200),
    status: Optional[str] = Query(None),
    permit_type: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Matches permit ref, type, issuer, or location"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Paginated permit list backing the "Total Permit List" table on both
    ActionsPage.tsx and EquipmentCertificationPage.tsx — every permit for
    this org, not a client-side-fabricated row count."""
    org_id = current_user.org_id

    base = (
        db.query(PermitToWork, PermitType, WorkingStation, Employee)
        .outerjoin(PermitType, org_scoped_join(PermitToWork.permit_type_id == PermitType.id, PermitType.organisation_id, org_id))
        .outerjoin(WorkingStation, org_scoped_join(PermitToWork.location_station_id == WorkingStation.id, WorkingStation.organisation_id, org_id))
        .outerjoin(Employee, org_scoped_join(PermitToWork.issued_by == Employee.id, Employee.organisation_id, org_id))
        .filter(*([PermitToWork.organisation_id == org_id] if org_id is not None else []))
    )
    if status and status != "All Status":
        base = base.filter(PermitToWork.status == status)
    if permit_type and permit_type != "All Types":
        base = base.filter(PermitType.permit_type_name == permit_type)
    if location and location != "All Locations":
        base = base.filter(WorkingStation.station_name == location)
    if q:
        like = f"%{q}%"
        conditions = [
            PermitToWork.work_description.ilike(like),
            PermitType.permit_type_name.ilike(like),
            Employee.full_name.ilike(like),
            WorkingStation.station_name.ilike(like),
        ]
        # The displayed permit ref is "PTW-{id}", not a stored column — match
        # digits typed/pasted from that ref (with or without the prefix)
        # against the real id so searching a shown ref actually finds it.
        digits = re.sub(r"[^0-9]", "", q)
        if digits:
            conditions.append(func.cast(PermitToWork.id, String).like(f"%{digits}%"))
        base = base.filter(or_(*conditions))

    total = base.count()
    rows = (
        base.order_by(case((PermitToWork.validity_end.is_(None), 1), else_=0), PermitToWork.validity_end.asc())
        .offset((page - 1) * pageSize)
        .limit(pageSize)
        .all()
    )

    def fmt_expiry(end_dt) -> str:
        if not end_dt:
            return "N/A"
        return end_dt.strftime("%b %d, %H:%M") if hasattr(end_dt, "hour") else end_dt.strftime("%b %d, %Y")

    data = [
        {
            "id": f"PTW-{ptw.id:04d}",
            "type": pt.permit_type_name if pt else "Unknown",
            "issued_by": emp.full_name if emp else "Unassigned",
            "location": ws.station_name if ws else (f"Station {ptw.location_station_id}" if ptw.location_station_id else "Unknown"),
            "status": ptw.status,
            "expiry": fmt_expiry(ptw.validity_end),
        }
        for ptw, pt, ws, emp in rows
    ]
    return {
        "data": data,
        "total": total,
        "page": page,
        "pageSize": pageSize,
        "totalPages": math.ceil(total / pageSize) if total else 0,
    }


@router.get("/permits/filter-options")
def get_permit_filter_options(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Distinct permit types and locations actually in use for this org, so
    the watchlist's filter dropdowns only ever offer real, selectable values."""
    org_id = current_user.org_id

    type_rows = (
        db.query(PermitType.permit_type_name)
        .join(PermitToWork, org_scoped_join(PermitToWork.permit_type_id == PermitType.id, PermitToWork.organisation_id, org_id))
        .filter(*([PermitType.organisation_id == org_id] if org_id is not None else []))
        .distinct()
        .order_by(PermitType.permit_type_name)
        .all()
    )
    location_rows = (
        db.query(WorkingStation.station_name)
        .join(PermitToWork, org_scoped_join(PermitToWork.location_station_id == WorkingStation.id, PermitToWork.organisation_id, org_id))
        .filter(*([WorkingStation.organisation_id == org_id] if org_id is not None else []))
        .distinct()
        .order_by(WorkingStation.station_name)
        .all()
    )
    return {
        "types": [r[0] for r in type_rows if r[0]],
        "locations": [r[0] for r in location_rows if r[0]],
    }


@router.get("/residual-risk-trend")
def get_residual_risk_trend(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    org_id = current_user.org_id

    latest_dt = _org_filter(db.query(func.max(Incident.incident_date_time)), Incident, org_id).scalar()
    # The day *after* the newest incident, so that incident lands inside the
    # final quarter. Anchoring on its own date excluded it: the last bucket is
    # half-open (`< q_end`) and q_end was the anchor, so whichever incident was
    # newest set the anchor and then filtered itself out. Every freshly reported
    # incident was therefore invisible here until a newer one replaced it —
    # which, for a trend the Risk page reads as current, is the one record that
    # matters most.
    anchor = (latest_dt.date() + timedelta(days=1)) if latest_dt else date.today()

    def _severity_weight(sev: str) -> int:
        s = (sev or "").lower()
        if "significant" in s:
            return 5
        if "lost time" in s or "major" in s:
            return 4
        if "serious" in s:
            return 3
        if "moderate" in s:
            return 2
        return 1

    quarter_days = 91
    raw_scores = []
    for i in range(3, -1, -1):
        q_end = anchor - timedelta(days=i * quarter_days)
        q_start = q_end - timedelta(days=quarter_days)
        rows = _org_filter(
            db.query(Incident.severity).filter(
                Incident.incident_date_time.isnot(None),
                Incident.incident_date_time >= q_start,
                Incident.incident_date_time < q_end,
            ),
            Incident, org_id,
        ).all()
        raw_scores.append(sum(_severity_weight(sev) for (sev,) in rows))

    max_raw = max(raw_scores) if any(raw_scores) else 1
    return [
        {"q": f"Q{i + 1}", "risk": round(score / max_raw * 100) if max_raw else 0}
        for i, score in enumerate(raw_scores)
    ]


@router.get("/risk-matrix")
def get_risk_matrix(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Risk matrix counts active (unresolved) hazards only.

    A hazard is considered RESOLVED and excluded from the matrix when:
    - All incidents linked to that hazard have investigation_status = 'Completed'
    - AND all CAPA actions for those incidents are status = 'Completed'
    This ensures closed risks vanish from the matrix automatically.
    """
    org_id = current_user.org_id

    def _sev_row(sev: str) -> Optional[int]:
        s = (sev or "").lower()
        if "fatal" in s or "catastrophic" in s:
            return 0
        if "significant" in s or "major" in s or "lost time" in s:
            return 1
        if "serious" in s or "high" in s:
            return 2
        if "moderate" in s or "medium" in s or "low" in s:
            return 3
        if "minor" in s or "negligible" in s:
            return 4
        return None

    def _prob_col(prob: str) -> Optional[int]:
        p = (prob or "").lower()
        if "frequent" in p or "almost certain" in p:
            return 0
        if "probable" in p or "likely" in p:
            return 1
        if "possible" in p or "occasional" in p:
            return 2
        if "unlikely" in p or "remote" in p:
            return 3
        if "rare" in p or "improbable" in p:
            return 4
        return None

    # ── Find hazard IDs that are fully resolved ───────────────────────────────
    # A hazard is resolved if every incident linked to it is completed AND
    # every CAPA for those incidents is completed.
    all_hazard_ids = [
        h.id for h in _org_filter(db.query(Hazard.id), Hazard, org_id).all()
    ]

    resolved_hazard_ids: set[int] = set()
    for hid in all_hazard_ids:
        linked_incidents = (
            db.query(Incident)
            .filter(
                Incident.hazard_id == hid,
                *([Incident.organisation_id == org_id] if org_id is not None else []),
            )
            .all()
        )
        if not linked_incidents:
            # No incidents linked — hazard stays on matrix (unverified)
            continue

        all_incidents_closed = all(
            ("complete" in (inc.investigation_status or "").lower() or
             "closed" in (inc.investigation_status or "").lower())
            for inc in linked_incidents
        )
        if not all_incidents_closed:
            continue

        # Check all CAPAs for these incidents are also completed
        inc_ids = [inc.id for inc in linked_incidents]
        open_capas = (
            db.query(CapaAction)
            .filter(
                CapaAction.incident_id.in_(inc_ids),
                (CapaAction.status.is_(None)) | func.lower(CapaAction.status).notin_(["completed", "closed", "verified", "done"]),
                *([CapaAction.organisation_id == org_id] if org_id is not None else []),
            )
            .count()
        )
        if open_capas == 0:
            resolved_hazard_ids.add(hid)

    # ── Build matrix from active (unresolved) hazards only ───────────────────
    hazards = (
        _org_filter(db.query(Hazard.id, Hazard.severity, Hazard.probability), Hazard, org_id)
        .all()
    )

    counts = [[0] * 5 for _ in range(5)]
    active_hazard_count = 0
    resolved_hazard_count = len(resolved_hazard_ids)

    for hid, sev, prob in hazards:
        if hid in resolved_hazard_ids:
            continue  # Skip resolved — auto-removed from matrix
        r = _sev_row(sev or "")
        c = _prob_col(prob or "")
        if r is not None and c is not None:
            counts[r][c] += 1
            active_hazard_count += 1

    return {
        "counts": counts,
        "active_hazard_count": active_hazard_count,
        "resolved_hazard_count": resolved_hazard_count,
        "total_hazard_count": len(hazards),
    }


@router.get("/risk-summary")
def get_risk_summary(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    org_id = current_user.org_id
    # Anchor "today" on this org's own latest CAPA due_date rather than the real
    # system clock — the seed data's due dates are all 2024-2025, so comparing
    # against a 2026 clock made every open action read as deeply overdue and
    # collapsed the whole aging chart into a single ">90 Days" bucket.
    today = (
        _org_filter(db.query(func.max(CapaAction.due_date)), CapaAction, org_id).scalar()
        or date.today()
    )

    zone_rows = (
        _org_filter(db.query(Site.site_name, func.count(Incident.id).label("cnt")), Site, org_id)
        .join(WorkingStation, org_scoped_join(WorkingStation.site_id == Site.id, WorkingStation.organisation_id, org_id))
        .join(Incident, org_scoped_join(Incident.location_station_id == WorkingStation.id, Incident.organisation_id, org_id))
        .filter(*([Incident.organisation_id == org_id] if org_id is not None else []))
        .group_by(Site.site_name)
        .order_by(func.count(Incident.id).desc())
        .limit(5)
        .all()
    )
    zone_risk = [{"zone": r.site_name, "value": r.cnt} for r in zone_rows]

    capa_rows = (
        _org_filter(
            db.query(CapaAction, Employee)
            .outerjoin(Employee, org_scoped_join(CapaAction.responsible_person_id == Employee.id, Employee.organisation_id, org_id))
            .filter((CapaAction.status.is_(None)) | func.lower(CapaAction.status).notin_(["completed", "closed", "verified", "done"])),
            CapaAction, org_id,
        )
        .order_by(case((CapaAction.due_date.is_(None), 1), else_=0), CapaAction.due_date.asc())
        .limit(10)  # Increased from 5 to match matrix total display
        .all()
    )

    def capa_status_label(c: CapaAction) -> str:
        # Real CAPA status, not a due_date-vs-today comparison — see the anchor
        # comment above for why the date math alone was unreliable here.
        if c.status == "Overdue":
            return "Overdue (Red)"
        if c.status == "In Progress":
            return "In Progress (Amber)"
        return "Pending (Yellow)"

    task_rows = [
        {
            "id": f"T-{c.id:03d}",
            "desc": c.description or c.action_type or "CAPA Action",
            "owner": emp.full_name if emp else "Unassigned",
            "due": c.due_date.strftime("%b %d, %Y") if c.due_date else "No Date",
            "status": capa_status_label(c),
        }
        for c, emp in capa_rows
    ]

    def aging_label(due_date) -> str:
        if not due_date:
            return ">90 Days"
        days_over = (today - due_date).days
        if days_over <= 30:
            return "0-30 Days"
        if days_over <= 60:
            return "31-60 Days"
        if days_over <= 90:
            return "61-90 Days"
        return ">90 Days"

    all_open = _org_filter(
        db.query(CapaAction).filter((CapaAction.status.is_(None)) | func.lower(CapaAction.status).notin_(["completed", "closed", "verified", "done"])),
        CapaAction, org_id,
    ).all()
    bucket_labels = ["0-30 Days", "31-60 Days", "61-90 Days", ">90 Days"]
    buckets: dict = {b: {"bucket": b, "low": 0, "medium": 0, "high": 0, "critical": 0, "line": 0} for b in bucket_labels}
    for c in all_open:
        bk = aging_label(c.due_date)
        buckets[bk]["line"] += 1
        if c.due_date:
            over = (today - c.due_date).days
            if over > 60:
                buckets[bk]["critical"] += 1
            elif over > 30:
                buckets[bk]["high"] += 1
            elif over > 0:
                buckets[bk]["medium"] += 1
            else:
                buckets[bk]["low"] += 1
        else:
            buckets[bk]["medium"] += 1
    aging_bars = list(buckets.values())

    capa_total = _org_filter(db.query(CapaAction), CapaAction, org_id).count()
    capa_done = _org_filter(
        db.query(CapaAction).filter(func.lower(CapaAction.status).in_(["completed", "closed", "verified", "done"])), CapaAction, org_id
    ).count()
    effectiveness = round((capa_done / capa_total * 100) if capa_total else 0)
    open_count = _org_filter(
        db.query(CapaAction).filter((CapaAction.status.is_(None)) | func.lower(CapaAction.status).notin_(["completed", "closed", "verified", "done"])), CapaAction, org_id
    ).count()
    # capa_workflow never writes status == "Overdue" — this table has no such
    # value, so filtering on it always returns 0 for live-workflow CAPAs.
    # Use the same "still open, past its due date" definition the aging
    # buckets above already use.
    overdue_count = sum(1 for c in all_open if c.due_date and c.due_date < today)

    # Risks closed in last 7 days (vanished from matrix + aging automatically)
    recently_closed_count = _org_filter(
        db.query(CapaAction).filter(
            func.lower(CapaAction.status).in_(["completed", "closed", "verified", "done"]),
            CapaAction.due_date >= today - timedelta(days=7),
        ),
        CapaAction, org_id,
    ).count()

    return {
        "zone_risk": zone_risk,
        "task_rows": task_rows,
        "aging_bars": aging_bars,
        "recently_closed_count": recently_closed_count,
        "kpis": {
            "control_effectiveness": f"{effectiveness}%",
            "unverified_controls": open_count,
            "risk_escalations": overdue_count,
        },
    }


def _rca_status(investigation_status: Optional[str]) -> str:
    s = (investigation_status or "").lower()
    if "complete" in s or "closed" in s:
        return "Closed"
    if "progress" in s:
        return "In Progress"
    return "Pending"


def _rca_priority(severity: Optional[str]) -> str:
    s = (severity or "").lower()
    if "fatal" in s or "catastrophic" in s or "critical" in s or "significant" in s:
        return "Critical"
    if "serious" in s or "high" in s or "major" in s or "lost time" in s:
        return "High"
    if "medium" in s or "moderate" in s:
        return "Medium"
    return "Low"


@router.get("/root-cause-analysis")
def get_root_cause_analysis(
    status: Optional[str] = None,
    site_id: Optional[str] = None,
    limit: int = Query(200, le=1000),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    org_id = current_user.org_id

    rows = (
        _org_filter(
            db.query(Incident, WorkingStation, Site, Employee)
            .outerjoin(WorkingStation, org_scoped_join(Incident.location_station_id == WorkingStation.id, WorkingStation.organisation_id, org_id))
            .outerjoin(Site, WorkingStation.site_id == Site.id)
            .outerjoin(Employee, org_scoped_join(Incident.reported_by == Employee.id, Employee.organisation_id, org_id)),
            Incident, org_id,
        )
        .order_by(Incident.id.desc())
        .limit(limit)
        .all()
    )

    incident_ids = [inc.id for inc, _, _, _ in rows]
    capa_rows = (
        _org_filter(
            db.query(CapaAction).filter(CapaAction.incident_id.in_(incident_ids)),
            CapaAction, org_id,
        ).all()
        if incident_ids
        else []
    )
    capa_by_incident: Dict[int, List[CapaAction]] = {}
    for c in capa_rows:
        capa_by_incident.setdefault(c.incident_id, []).append(c)

    results = []
    for inc, ws, site, emp in rows:
        rca_status = _rca_status(inc.investigation_status)
        capas = capa_by_incident.get(inc.id, [])
        preventive = [c.description for c in capas if c.description and "prevent" in (c.action_type or "").lower()]
        corrective = [c.description for c in capas if c.description and c.description not in preventive]

        completion_date = None
        if rca_status == "Closed":
            completed_due_dates = [c.due_date for c in capas if c.due_date and (c.status or "").lower() == "completed"]
            any_due_dates = [c.due_date for c in capas if c.due_date]
            if completed_due_dates:
                completion_date = max(completed_due_dates)
            elif any_due_dates:
                completion_date = max(any_due_dates)

        start_date = ""
        if inc.incident_date_time:
            start_date = inc.incident_date_time.date().isoformat()
        elif inc.report_date:
            start_date = inc.report_date.isoformat()

        results.append({
            "RCA_ID": f"RCA-{inc.id:04d}",
            "Incident_ID": f"INC-{inc.id:05d}",
            "Incident_Type": inc.incident_type or "Unknown",
            "Site_ID": site.site_name if site else "—",
            "Zone_ID": ws.zone_classification if ws else "—",
            "Conducted_By": emp.full_name if emp else "Unknown",
            "Start_Date": start_date,
            "Completion_Date": completion_date.isoformat() if completion_date else "",
            "Root_Causes": inc.root_cause or inc.root_cause_category or "Under investigation",
            "Contributing_Factors": inc.immediate_cause or "—",
            "Corrective_Actions": "; ".join(corrective) if corrective else "—",
            "Preventive_Measures": "; ".join(preventive) if preventive else "—",
            "Status": rca_status,
            "Priority": _rca_priority(inc.severity),
        })

    if status:
        results = [r for r in results if r["Status"] == status]
    if site_id:
        results = [r for r in results if r["Site_ID"] == site_id]

    return results


@router.get("/compliance-summary")
def get_compliance_summary(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    org_id = current_user.org_id

    total_permits = _org_filter(db.query(PermitToWork), PermitToWork, org_id).count()
    # Excel KPI spec (M4_Assets_Operations): PTW Compliance Rate = Closed / Total × 100
    closed_permits = _org_filter(
        db.query(PermitToWork).filter(PermitToWork.status == "Closed"),
        PermitToWork, org_id,
    ).count()
    permit_compliance_pct = round(closed_permits / total_permits * 100) if total_permits else 0

    # Excel KPI spec (M4_Assets_Operations): LOTO Compliance % (PROXY) =
    # Lockout/Isolation permits with no deviation reported ÷ Lockout/Isolation permits issued × 100
    # Not a true field-audit result — indicative only, per client's own methodology note.
    lockout_permits_q = (
        _org_filter(db.query(PermitToWork), PermitToWork, org_id)
        .join(PermitType, org_scoped_join(PermitToWork.permit_type_id == PermitType.id, PermitType.organisation_id, org_id))
        .filter(PermitType.permit_type_name == "Equipment Isolation/Lockout")
    )
    total_lockout_permits = lockout_permits_q.count()
    lockout_no_deviation = lockout_permits_q.filter(PermitToWork.deviation_reported == "No").count()
    loto_compliance_pct = (
        round(lockout_no_deviation / total_lockout_permits * 100) if total_lockout_permits else None
    )

    total_policies = _org_filter(db.query(Policy), Policy, org_id).count()
    current_policies = _org_filter(
        db.query(Policy).filter(Policy.status == "Current"), Policy, org_id
    ).count()
    policy_review_pct = round(current_policies / total_policies * 100) if total_policies else 0

    # Excel KPI spec (M2_Risk_Hazards): Corrective Action Closure Rate =
    # CAPA Actions Completed ÷ Total CAPA Actions × 100 — the one Module 2 KPI the client's
    # own spec marks as computable (all other Module 2 Risk KPIs need a structured risk register).
    total_capa = _org_filter(db.query(CapaAction), CapaAction, org_id).count()
    completed_capa = _org_filter(
        db.query(CapaAction).filter(func.lower(CapaAction.status).in_(["completed", "closed", "verified", "done"])), CapaAction, org_id
    ).count()
    corrective_action_closure_rate = round(completed_capa / total_capa * 100, 1) if total_capa else 0

    distinct_policy_categories = _org_filter(
        db.query(func.count(func.distinct(Policy.category))), Policy, org_id
    ).scalar() or 0
    # Each org defines its own hazard categories — an unscoped count here mixes
    # every tenant's category names into one denominator (18 distinct names
    # across all orgs vs. ~10 for any one org), understating every org's real
    # coverage against its own hazard register.
    distinct_hazard_categories = _org_filter(
        db.query(func.count(func.distinct(HazardCategory.category_name))), HazardCategory, org_id
    ).scalar() or 0
    legal_register_pct = (
        min(100, round(distinct_policy_categories / distinct_hazard_categories * 100))
        if distinct_hazard_categories else 0
    )

    # Single shared implementation, see app/services/audit_readiness.py (same
    # score dashboard.py's leading-indicators panel shows).
    audit_readiness = compute_audit_readiness(db, org_id)
    audit_readiness_pct = audit_readiness.score

    compliance_score = round((permit_compliance_pct + legal_register_pct + audit_readiness_pct) / 3)
    legal_label = "High" if legal_register_pct >= 85 else ("Medium" if legal_register_pct >= 60 else "Low")
    # Client feedback (Compliance Section): "unnecessary classification lines
    # should be removed... existing explanatory text was considered useful and
    # could potentially be reused... instead of generic labels such as 'Needs
    # Attention'." These describe what actually feeds the number instead of
    # re-classifying it — the same pattern already used on the LOTO and
    # Policy-Hazard cards below.
    compliance_label = (
        f"Blend of permit closure ({permit_compliance_pct}%), policy coverage "
        f"({legal_register_pct}%) & audit readiness ({audit_readiness_pct}%)"
    )
    audit_label = audit_readiness.note

    # ── Previous-period comparison ───────────────────────────────────────────
    # Client correction: "not previous year, previous period" — the preceding
    # window of the same length (here, trailing 12 months), anchored to the
    # latest real activity in this org's own data rather than literal today
    # (seed data doesn't reach today's date, so a literal-today anchor would
    # show zero activity in both windows for every org — same reasoning as
    # the leading-indicators trend window in dashboard.py).
    def _as_date(d):
        return d.date() if hasattr(d, "date") else d

    activity_dates = [
        _as_date(d) for d in (
            _org_filter(db.query(func.max(PermitToWork.date_issued)), PermitToWork, org_id).scalar(),
            _org_filter(db.query(func.max(CapaAction.created_at)), CapaAction, org_id).scalar(),
            _org_filter(db.query(func.max(SafetyWalk.inspection_date_time)), SafetyWalk, org_id).scalar(),
            _org_filter(db.query(func.max(Audit.scheduled_date)), Audit, org_id).scalar(),
        ) if d is not None
    ]
    latest_activity = max(activity_dates) if activity_dates else date.today()
    current_period_start = latest_activity - timedelta(days=365)
    previous_period_start = latest_activity - timedelta(days=730)

    def _permit_compliance_window(start, end):
        q = _org_filter(db.query(PermitToWork), PermitToWork, org_id).filter(
            func.date(PermitToWork.date_issued) > start, func.date(PermitToWork.date_issued) <= end,
        )
        total = q.count()
        if not total:
            return None
        return round(q.filter(PermitToWork.status == "Closed").count() / total * 100)

    def _capa_closure_window(start, end):
        q = _org_filter(db.query(CapaAction), CapaAction, org_id).filter(
            func.date(CapaAction.created_at) > start, func.date(CapaAction.created_at) <= end,
        )
        total = q.count()
        if not total:
            return None
        closed = q.filter(func.lower(CapaAction.status).in_(["completed", "closed", "verified", "done"])).count()
        return round(closed / total * 100, 1)

    def _audit_readiness_window(start, end):
        components = []
        walk_avg = (
            _org_filter(db.query(func.avg(SafetyWalk.compliance_rating)), SafetyWalk, org_id)
            .filter(func.date(SafetyWalk.inspection_date_time) > start, func.date(SafetyWalk.inspection_date_time) <= end)
            .scalar()
        )
        if walk_avg is not None:
            components.append(float(walk_avg) / 5 * 100)
        audit_avg = (
            _org_filter(db.query(func.avg(Audit.compliance_score)), Audit, org_id)
            .filter(Audit.compliance_score.isnot(None))
            .filter(func.date(Audit.scheduled_date) > start, func.date(Audit.scheduled_date) <= end)
            .scalar()
        )
        if audit_avg is not None:
            components.append(float(audit_avg))
        return round(sum(components) / len(components)) if components else None

    def _delta(current, previous):
        return None if current is None or previous is None else round(current - previous, 1)

    permit_compliance_current = _permit_compliance_window(current_period_start, latest_activity)
    permit_compliance_previous = _permit_compliance_window(previous_period_start, current_period_start)
    corrective_action_current = _capa_closure_window(current_period_start, latest_activity)
    corrective_action_previous = _capa_closure_window(previous_period_start, current_period_start)
    audit_readiness_current = _audit_readiness_window(current_period_start, latest_activity)
    audit_readiness_previous = _audit_readiness_window(previous_period_start, current_period_start)

    compliance_score_components_current = [v for v in (permit_compliance_current, audit_readiness_current) if v is not None]
    compliance_score_components_previous = [v for v in (permit_compliance_previous, audit_readiness_previous) if v is not None]
    compliance_score_current = (
        round(sum(compliance_score_components_current) / len(compliance_score_components_current))
        if compliance_score_components_current else None
    )
    compliance_score_previous = (
        round(sum(compliance_score_components_previous) / len(compliance_score_components_previous))
        if compliance_score_components_previous else None
    )

    latest_walk_date = _org_filter(
        db.query(func.max(SafetyWalk.inspection_date_time)), SafetyWalk, org_id
    ).scalar()
    trend_rows = (
        _org_filter(
            db.query(
                func.year(SafetyWalk.inspection_date_time).label("yr"),
                func.month(SafetyWalk.inspection_date_time).label("mo"),
                func.avg(SafetyWalk.compliance_rating).label("avg_rating"),
            ).filter(SafetyWalk.inspection_date_time.isnot(None)),
            SafetyWalk, org_id,
        )
        .group_by("yr", "mo")
        .order_by("yr", "mo")
        .all()
    ) if latest_walk_date else []
    # A month whose walks all carry a NULL compliance_rating averages to NULL,
    # and float(None) took the whole Compliance page down with a 500. The mobile
    # app logs walks without a rating, so this fires as soon as one is submitted
    # in the current month — it is a live condition, not a legacy-data edge case.
    #
    # Such a month is dropped rather than plotted as 0: nobody rated those walks,
    # and 0 renders as total non-compliance, which is a different and much worse
    # claim than "not measured".
    compliance_trend = [
        {"month": MONTH_NAMES[int(r.mo) - 1], "value": round(float(r.avg_rating) / 5 * 100)}
        for r in trend_rows[-10:]
        if r.avg_rating is not None
    ]
    trend_mom = None
    if len(compliance_trend) >= 2:
        prev, curr = compliance_trend[-2]["value"], compliance_trend[-1]["value"]
        trend_mom = curr - prev

    # Genuinely from the WF-05 audit workflow's own classification, not a
    # Safety Walk issue-count heuristic standing in for it. The card is titled
    # "Audit Findings by Severity" — it used to build that count out of
    # SafetyWalk.critical_issues/issues_found thresholds, which have no
    # relationship to an auditor's actual conformance/observation/minor_nc/
    # major_nc/critical classification. Conformances are excluded here: they
    # are the audit's passing results, not a severity of finding.
    audit_finding_counts = dict(
        _org_filter(
            db.query(AuditFinding.classification, func.count(AuditFinding.id)), AuditFinding, org_id,
        )
        .filter(AuditFinding.classification != "conformance")
        .group_by(AuditFinding.classification)
        .all()
    )
    findings_by_severity = [
        {"name": "Critical", "value": audit_finding_counts.get("critical", 0), "color": "#5A7895"},
        {"name": "Major", "value": audit_finding_counts.get("major_nc", 0), "color": "#5E67A9"},
        {"name": "Minor", "value": audit_finding_counts.get("minor_nc", 0), "color": "#E6AF37"},
        {"name": "Observation", "value": audit_finding_counts.get("observation", 0), "color": "#5E7399"},
    ]

    nc_rows = (
        _org_filter(
            db.query(CapaAction, Employee, Incident)
            .outerjoin(Employee, org_scoped_join(CapaAction.responsible_person_id == Employee.id, Employee.organisation_id, org_id))
            .outerjoin(Incident, CapaAction.incident_id == Incident.id)
            .filter((CapaAction.status.is_(None)) | func.lower(CapaAction.status).notin_(["completed", "closed", "verified", "done"])),
            CapaAction, org_id,
        )
        .order_by(case((CapaAction.due_date.is_(None), 1), else_=0), CapaAction.due_date.asc())
        .limit(6)
        .all()
    )
    priority_to_criticality = {"Critical": "High", "High": "High", "Medium": "Medium", "Low": "Low"}
    non_conformance_rows = [
        {
            "id": f"NC-{c.id:03d}",
            "capa_id": c.id,
            "action": _clean_capa_description(c),
            "owner": emp.full_name if emp else "Unassigned",
            "due": c.due_date.strftime("%b %d, %Y") if c.due_date else "No Date",
            "criticality": priority_to_criticality.get(_rca_priority(inc.severity if inc else None), "Low"),
        }
        for c, emp, inc in nc_rows
    ]

    return {
        "compliance_score": compliance_score,
        "compliance_label": compliance_label,
        "compliance_score_prev_12mo_delta": _delta(compliance_score_current, compliance_score_previous),
        "legal_register_coverage_pct": legal_register_pct,
        "legal_register_label": legal_label,
        "audit_readiness_pct": audit_readiness_pct,
        "audit_readiness_label": audit_label,
        "audit_readiness_prev_12mo_delta": _delta(audit_readiness_current, audit_readiness_previous),
        "permit_compliance_pct": permit_compliance_pct,
        "permit_compliance_prev_12mo_delta": _delta(permit_compliance_current, permit_compliance_previous),
        "loto_compliance_pct": loto_compliance_pct,
        "corrective_action_closure_rate": corrective_action_closure_rate,
        "corrective_action_closure_prev_12mo_delta": _delta(corrective_action_current, corrective_action_previous),
        "policy_review_pct": policy_review_pct,
        "compliance_trend": compliance_trend,
        "compliance_trend_mom": trend_mom,
        "findings_by_severity": findings_by_severity,
        "non_conformance_rows": non_conformance_rows,
    }


@router.get("/asset-summary")
def get_asset_summary(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    from datetime import timedelta
    from app.models.equipment_certification import EquipmentCertification

    org_id = current_user.org_id
    today = date.today()

    # ── Equipment cert counts ─────────────────────────────────────────────────
    cert_q = db.query(EquipmentCertification)
    if org_id is not None:
        cert_q = cert_q.filter(EquipmentCertification.organisation_id == org_id)
    all_certs = cert_q.all()

    total_certs = len(all_certs)

    def _cert_status(expiry_date):
        if not expiry_date:
            return "Valid"
        if expiry_date < today:
            return "Expired"
        if expiry_date <= today + timedelta(days=30):
            return "Expiring Soon"
        return "Valid"

    for c in all_certs:
        c._status = _cert_status(c.expiry_date)

    valid_count        = sum(1 for c in all_certs if c._status == "Valid")
    expiring_count     = sum(1 for c in all_certs if c._status == "Expiring Soon")
    expired_count      = sum(1 for c in all_certs if c._status == "Expired")

    control_effectiveness = round(valid_count / total_certs * 100) if total_certs else 0
    maintenance_risk_pct  = round((expiring_count + expired_count) / total_certs * 100) if total_certs else 0
    risk_label, _ = label_and_tone(maintenance_risk_pct, get_rating_labels(db, org_id), "asset_maintenance_risk")

    # ── Incident trend by month (asset context = all incidents) ───────────────
    inc_rows = (
        _org_filter(
            db.query(
                func.year(Incident.incident_date_time).label("yr"),
                func.month(Incident.incident_date_time).label("mo"),
                func.count(Incident.id).label("cnt"),
            ).filter(Incident.incident_date_time.isnot(None)),
            Incident, org_id,
        )
        .group_by("yr", "mo")
        .order_by("yr", "mo")
        .all()
    )
    failure_trend = [{"month": MONTH_NAMES[int(r.mo) - 1], "value": r.cnt} for r in inc_rows[-8:]]

    nm_rows = (
        _org_filter(
            db.query(
                func.year(NearMiss.event_date_time).label("yr"),
                func.month(NearMiss.event_date_time).label("mo"),
                func.count(NearMiss.id).label("cnt"),
            ).filter(NearMiss.event_date_time.isnot(None)),
            NearMiss, org_id,
        )
        .group_by("yr", "mo")
        .order_by("yr", "mo")
        .all()
    )
    asset_incident_trend = [{"month": MONTH_NAMES[int(r.mo) - 1], "value": r.cnt} for r in nm_rows[-8:]]

    # ── Risk table — certs that are expired or expiring soon ──────────────────
    risk_certs = [c for c in all_certs if c._status in ("Expired", "Expiring Soon")][:6]
    risk_table = [
        {
            "id": f"CERT-{c.id:04d}",
            "type": c.equipment_type or "Unknown",
            "risk": "High" if c._status == "Expired" else "Medium",
            "status": "Critical (Red)" if c._status == "Expired" else "Warning (Amber)",
        }
        for c in risk_certs
    ]

    # ── Overdue inspections — certs where next_inspection_date < today ────────
    overdue_certs = [
        c for c in all_certs
        if c.next_inspection_date and c.next_inspection_date < today
    ]
    overdue_certs.sort(key=lambda c: c.next_inspection_date)

    def _overdue_label(d: date) -> str:
        days = (today - d).days
        if days == 0:
            return "Due Today"
        if days == 1:
            return "Due Yesterday"
        return f"Due {days} Days Ago"

    overdue_inspections = [
        {
            "name": f"{c.equipment_name} Inspection",
            "due": _overdue_label(c.next_inspection_date),
            "tone": "critical",
        }
        for c in overdue_certs[:5]
    ]

    # ── Barrier checklist — cert types with their completion ratio ────────────
    type_counts: Dict[str, dict] = {}
    for c in all_certs:
        t = c.certification_type or "General"
        if t not in type_counts:
            type_counts[t] = {"total": 0, "valid": 0}
        type_counts[t]["total"] += 1
        if c._status == "Valid":
            type_counts[t]["valid"] += 1
    barrier_checklist = [
        {
            "text": ctype,
            "progress": round(v["valid"] / v["total"] * 100) if v["total"] else 0,
        }
        for ctype, v in list(type_counts.items())[:5]
    ]

    # ── Heat map — equipment type vs site ─────────────────────────────────────
    site_ids = {c.site_id for c in all_certs if c.site_id}
    site_map: Dict[int, str] = {}
    if site_ids:
        for s in db.query(Site).filter(Site.id.in_(site_ids)).all():
            site_map[s.id] = s.site_name

    types_list  = sorted({c.equipment_type or "Unknown" for c in all_certs})[:6]
    sites_list  = sorted({site_map.get(c.site_id, "Unknown") for c in all_certs})[:6]

    heat_vals: List[List[float]] = []
    for t in types_list:
        row_vals = []
        for s in sites_list:
            bucket = [
                c for c in all_certs
                if (c.equipment_type or "Unknown") == t
                and site_map.get(c.site_id, "Unknown") == s
            ]
            if not bucket:
                row_vals.append(0.1)
            else:
                expired_ratio = sum(1 for c in bucket if c._status == "Expired") / len(bucket)
                row_vals.append(round(expired_ratio + 0.1, 2))
        heat_vals.append(row_vals)

    return {
        "control_effectiveness_pct": control_effectiveness,
        "maintenance_risk_pct": maintenance_risk_pct,
        "maintenance_risk_label": risk_label,
        "total_certs": total_certs,
        "valid_count": valid_count,
        "expiring_count": expiring_count,
        "expired_count": expired_count,
        "failure_trend": failure_trend,
        "asset_incident_trend": asset_incident_trend,
        "risk_table": risk_table,
        "overdue_inspections": overdue_inspections,
        "barrier_checklist": barrier_checklist,
        "heat_rows": types_list,
        "heat_cols": sites_list,
        "heat_vals": heat_vals,
    }


@router.get("/engagement-summary")
def get_engagement_summary(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    from app.models.user import User
    from app.models.app_role import AppRole

    org_id = current_user.org_id
    today = date.today()
    first_this_month = today.replace(day=1)
    first_last_month = (first_this_month - timedelta(days=1)).replace(day=1)

    def _report_count(from_dt, to_dt):
        inc = int(
            _org_filter(
                db.query(func.count(Incident.id)).filter(
                    Incident.report_date >= from_dt, Incident.report_date < to_dt
                ),
                Incident, org_id,
            ).scalar() or 0
        )
        nm = int(
            _org_filter(
                db.query(func.count(NearMiss.id)).filter(
                    func.date(NearMiss.event_date_time) >= from_dt,
                    func.date(NearMiss.event_date_time) < to_dt,
                ),
                NearMiss, org_id,
            ).scalar() or 0
        )
        return inc + nm

    this_month_reports = _report_count(first_this_month, today + timedelta(days=1))
    last_month_reports = _report_count(first_last_month, first_this_month)

    total_employees = int(
        _org_filter(db.query(func.count(Employee.id)), Employee, org_id).scalar() or 0
    )
    # Reporting rate: reports-per-employee scaled; fallback to raw count when no employees
    if total_employees > 0:
        reporting_rate = min(100, round(this_month_reports / total_employees * 25))
    else:
        reporting_rate = min(100, this_month_reports * 10)
    reporting_rate_mom = this_month_reports - last_month_reports

    # Survey score — avg compliance_rating from safety_walks (1–5 scale)
    avg_compliance = _org_filter(
        db.query(func.avg(SafetyWalk.compliance_rating)), SafetyWalk, org_id
    ).scalar()
    survey_score = round(float(avg_compliance or 0), 1)
    survey_score_pct = round(survey_score / 5 * 100)

    avg_this_month = _org_filter(
        db.query(func.avg(SafetyWalk.compliance_rating)).filter(
            func.date(SafetyWalk.inspection_date_time) >= first_this_month
        ),
        SafetyWalk, org_id,
    ).scalar()
    avg_last_month = _org_filter(
        db.query(func.avg(SafetyWalk.compliance_rating)).filter(
            func.date(SafetyWalk.inspection_date_time) >= first_last_month,
            func.date(SafetyWalk.inspection_date_time) < first_this_month,
        ),
        SafetyWalk, org_id,
    ).scalar()
    if avg_this_month is not None and avg_last_month is not None:
        survey_score_mom = round(float(avg_this_month) - float(avg_last_month), 1)
    else:
        survey_score_mom = None

    # Safety observations % — walks with high compliance (rating >= 4)
    total_walks = int(
        _org_filter(db.query(func.count(SafetyWalk.id)), SafetyWalk, org_id).scalar() or 0
    )
    compliant_walks = int(
        _org_filter(
            db.query(func.count(SafetyWalk.id)).filter(SafetyWalk.compliance_rating >= 4),
            SafetyWalk, org_id,
        ).scalar() or 0
    )
    safety_observations_pct = round(compliant_walks / max(total_walks, 1) * 100)

    # Safety walks % — walks completed this month vs one-per-employee target.
    # Fall back to all-time walks when no walks exist this month
    # (imported historical data often has past dates).
    walks_this_month = int(
        _org_filter(
            db.query(func.count(SafetyWalk.id)).filter(
                func.date(SafetyWalk.inspection_date_time) >= first_this_month
            ),
            SafetyWalk, org_id,
        ).scalar() or 0
    )
    effective_walks = walks_this_month if walks_this_month > 0 else total_walks
    safety_walks_pct = min(100, round(effective_walks / max(total_employees, 1) * 100))

    # Toolbox attendance % — toolbox-type walks vs employee count
    # Fall back to all walk types when no "toolbox" entries exist
    toolbox_count = int(
        _org_filter(
            db.query(func.count(SafetyWalk.id)).filter(
                func.lower(SafetyWalk.inspection_type).like("%toolbox%")
            ),
            SafetyWalk, org_id,
        ).scalar() or 0
    )
    if toolbox_count == 0:
        toolbox_count = total_walks
    toolbox_pct = min(100, round(toolbox_count / max(total_employees, 1) * 100))

    # Site participation % — distinct sites with incidents or near_misses vs total sites
    total_sites = int(
        _org_filter(db.query(func.count(Site.id)), Site, org_id).scalar() or 0
    )
    active_sites_inc = int(
        db.query(func.count(func.distinct(WorkingStation.site_id)))
        .join(Incident, Incident.location_station_id == WorkingStation.id)
        .filter(*(
            [Incident.organisation_id == org_id]
            if org_id is not None else []
        ))
        .scalar() or 0
    )
    active_sites_nm = int(
        db.query(func.count(func.distinct(WorkingStation.site_id)))
        .join(NearMiss, NearMiss.location_station_id == WorkingStation.id)
        .filter(*(
            [NearMiss.organisation_id == org_id]
            if org_id is not None else []
        ))
        .scalar() or 0
    )
    active_sites = min(max(active_sites_inc, active_sites_nm), total_sites)
    site_participation_pct = round(active_sites / max(total_sites, 1) * 100)

    # Top recognitions — employees with most completed CAPA actions
    top_emp_rows = (
        db.query(Employee.full_name, func.count(CapaAction.id).label("cnt"))
        .join(CapaAction, org_scoped_join(CapaAction.responsible_person_id == Employee.id, CapaAction.organisation_id, org_id))
        .filter(
            func.lower(CapaAction.status).in_(["completed", "closed", "verified", "done"]),
            *(
                [Employee.organisation_id == org_id]
                if org_id is not None else []
            ),
        )
        .group_by(Employee.full_name)
        .order_by(func.count(CapaAction.id).desc())
        .limit(3)
        .all()
    )
    top_recognitions = [{"name": r.full_name} for r in top_emp_rows if r.full_name]

    # Fallback: use org users when employees table is empty
    if not top_recognitions:
        user_rows = (
            db.query(User, AppRole)
            .outerjoin(AppRole, User.app_role_id == AppRole.id)
            .filter(
                User.organisation_id == org_id,
                AppRole.name.notin_(["superadmin", "admin"]),
            )
            if org_id is not None
            else db.query(User, AppRole)
            .outerjoin(AppRole, User.app_role_id == AppRole.id)
            .filter(AppRole.name.notin_(["superadmin", "admin"]))
        )
        top_recognitions = [
            {"name": u.full_name or u.username}
            for u, _ in user_rows.order_by(User.id.asc()).limit(3).all()
        ]

    # Open actions — CAPA not completed, ordered by due date
    def _action_status(due_date) -> str:
        if not due_date:
            return "Overdue"
        days = (due_date - today).days
        if days < 0:
            return "Overdue"
        if days == 0:
            return "Due Today"
        return "Due Tomorrow"

    open_capa_rows = (
        _org_filter(
            db.query(CapaAction).filter((CapaAction.status.is_(None)) | func.lower(CapaAction.status).notin_(["completed", "closed", "verified", "done"])),
            CapaAction, org_id,
        )
        .order_by(
            case((CapaAction.due_date.is_(None), 1), else_=0),
            CapaAction.due_date.asc(),
        )
        .limit(5)
        .all()
    )
    open_actions = [
        {
            "text": _clean_capa_description(c),
            "status": _action_status(c.due_date),
        }
        for c in open_capa_rows
    ]

    return {
        "reporting_rate": reporting_rate,
        "reporting_rate_mom": reporting_rate_mom,
        "survey_score": survey_score,
        "survey_score_pct": survey_score_pct,
        "survey_score_mom": survey_score_mom,
        "safety_observations_pct": safety_observations_pct,
        "safety_walks_pct": safety_walks_pct,
        "toolbox_attendance_pct": toolbox_pct,
        "site_participation_pct": site_participation_pct,
        "top_recognitions": top_recognitions,
        "open_actions": open_actions,
    }


@router.get("/violation-detail/{incident_id}")
def get_violation_detail(
    incident_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    org_id = current_user.org_id

    row = (
        db.query(Incident, WorkingStation, Site, Employee)
        .outerjoin(WorkingStation, org_scoped_join(Incident.location_station_id == WorkingStation.id, WorkingStation.organisation_id, org_id))
        .outerjoin(Site, WorkingStation.site_id == Site.id)
        .outerjoin(Employee, org_scoped_join(Incident.reported_by == Employee.id, Employee.organisation_id, org_id))
        .filter(Incident.id == incident_id)
        .filter(*([Incident.organisation_id == org_id] if org_id is not None else []))
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Incident not found")

    inc, ws, site, reporter = row

    capa_rows = (
        db.query(CapaAction, Employee)
        .outerjoin(Employee, org_scoped_join(CapaAction.responsible_person_id == Employee.id, Employee.organisation_id, org_id))
        .filter(CapaAction.incident_id == inc.id)
        .order_by(CapaAction.due_date.asc())
        .all()
    )

    capa_list = [
        {
            "id": c.capa_ref or f"CAPA-{c.id:06d}",
            "action_type": c.action_type or "Corrective Action",
            "description": _clean_capa_description(c),
            "responsible_person": emp.full_name if emp else "Unassigned",
            "due_date": c.due_date.strftime("%b %d, %Y") if c.due_date else None,
            "status": c.status or "Pending",
        }
        for c, emp in capa_rows
    ]

    def _status_step(s: str) -> int:
        sl = (s or "").lower()
        if "complete" in sl or "closed" in sl:
            return 4
        if "progress" in sl:
            return 3
        if "acknowledge" in sl:
            return 2
        if "assign" in sl:
            return 1
        return 0

    def _map_severity(sev: str) -> str:
        s = (sev or "").lower()
        if "fatal" in s or "critical" in s or "catastrophic" in s or "significant" in s:
            return "Critical"
        if "major" in s or "lost time" in s or "high" in s or "serious" in s:
            return "High"
        if "moderate" in s or "medium" in s:
            return "Medium"
        return "Low"

    def _fmt_dt(dt_val) -> str:
        if dt_val is None:
            return "Unknown"
        if hasattr(dt_val, "hour"):
            return dt_val.strftime("%b %d, %Y %I:%M %p")
        return dt_val.strftime("%b %d, %Y")

    timeline = []
    if inc.incident_date_time or inc.report_date:
        timeline.append({
            "action": "Incident Reported",
            "user": reporter.full_name if reporter else "System",
            "time": _fmt_dt(inc.incident_date_time or inc.report_date),
            "type": "reported",
        })
    for c, emp in capa_rows:
        timeline.append({
            "action": f"CAPA: {_clean_capa_description(c)}",
            "user": emp.full_name if emp else "Unassigned",
            "time": c.due_date.strftime("%b %d, %Y") if c.due_date else "No date",
            "type": "capa",
        })
    inv_status = inc.investigation_status or "Pending"
    if ("complete" in inv_status.lower() or "closed" in inv_status.lower()) and timeline:
        timeline.append({
            "action": "Investigation Closed",
            "user": "System",
            "time": _fmt_dt(inc.incident_date_time or inc.report_date),
            "type": "closed",
        })

    assignee = None
    if capa_rows:
        _, first_emp = capa_rows[0]
        if first_emp:
            assignee = {"name": first_emp.full_name, "role": "Responsible Person"}

    first_due = (
        capa_rows[0][0].due_date.strftime("%Y-%m-%d")
        if capa_rows and capa_rows[0][0].due_date
        else None
    )

    return {
        "id": f"INC-{inc.id:05d}",
        "source": inc.source,
        "incident_type": inc.incident_type or "Unknown",
        "severity": _map_severity(inc.severity or ""),
        "raw_severity": inc.severity or "Unknown",
        "investigation_status": inv_status,
        "status_step": _status_step(inv_status),
        "incident_datetime": _fmt_dt(inc.incident_date_time or inc.report_date),
        "description": inc.description or "",
        "immediate_cause": inc.immediate_cause or "—",
        "root_cause": inc.root_cause or inc.root_cause_category or "Under investigation",
        "zone": ws.zone_classification if ws else "—",
        "station": ws.station_name if ws else "—",
        "site": site.site_name if site else "—",
        "reporter": reporter.full_name if reporter else "Unknown",
        "permit_active": inc.permit_active or "No",
        "days_away": inc.days_away or 0,
        "number_persons_involved": inc.number_persons_involved or 0,
        "control_failure": inc.control_failure or "No",
        "capa_actions": capa_list,
        "timeline": timeline,
        "assignee": assignee,
        "due_date": first_due,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Risk reports (`risk_reports`) — the Risk section's own data
# ══════════════════════════════════════════════════════════════════════════════
#
# Separate from /risk-matrix and /risk-summary above, which read `hazards` and
# `incidents`. Those two are the whole reason this endpoint exists: the console's
# Risk page was built on them and so contained no risk report at all — the
# register's matrix and the incident zone heatmap under a heading that promised
# risk. Both are left exactly as they are; the mobile manager's Risk tab and
# controllers/ai.py read them, and neither is wrong about what it plots, only
# about what the page around it claimed.
#
# The axes come from `risk_scoring.LIKELIHOOD` / `.SEVERITY` rather than a
# mapping of this module's own. That module already exists to make "the API, the
# mobile form and the gate engine all resolve the same words to the same
# integers", and a fourth private vocabulary here would be the thing it was
# written to prevent. It also makes this matrix genuinely numeric — the hazard
# matrix has to hedge that it is a "qualitative estimate from severity text",
# because `hazards` carries no score; `risk_reports` carries L x S outright.


# The grid's axes, worst first, as the client labels them. Written out rather
# than derived by sorting `risk_scoring.SEVERITY` / `.LIKELIHOOD`: both dicts
# hold synonyms on the same integer (critical/catastrophic at 5, and two
# spellings of almost_certain), so a sort would pick a label by dict order.
# The `value` of each entry is the 1-5 score, which is what ties these labels
# back to the scale and lets a reader check the order at a glance.
_SEVERITY_AXIS = [
    {"label": "Critical", "score": 5},
    {"label": "Major", "score": 4},
    {"label": "Moderate", "score": 3},
    {"label": "Minor", "score": 2},
    {"label": "Negligible", "score": 1},
]
_LIKELIHOOD_AXIS = [
    {"label": "Almost certain", "score": 5},
    {"label": "Likely", "score": 4},
    {"label": "Possible", "score": 3},
    {"label": "Unlikely", "score": 2},
    {"label": "Rare", "score": 1},
]


def _risk_axis_index(value: Optional[str], scale: Dict[str, int]) -> Optional[int]:
    """Word -> 0-based grid index, worst first.

    The grid is drawn worst-to-best in both directions (row 0 is the most severe
    consequence, column 0 the most likely), while the scoring scale runs 1-5
    best-to-worst — hence `5 - n`. Returns None for a word the scale does not
    know, so it is counted as unscored rather than silently landing in a cell.
    """
    n = scale.get((value or "").strip().lower())
    return (5 - n) if n else None


@router.get("/risk-report-matrix")
def get_risk_report_matrix(
    include_closed: bool = Query(False, description="Count closed risks too"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """The 5x5 matrix, band split and headline counts for `risk_reports`.

    `counts[row][col]` is indexed exactly like the hazard matrix the console
    already renders — row 0 the most severe consequence, column 0 the most
    likely — so one grid component draws either source.

    Open by default. A closed risk has been dealt with and leaving it on the
    matrix would make the site look permanently worse than it is; the same
    reasoning excludes resolved hazards from /risk-matrix.
    """
    from app.models.risk_report import RiskReport
    from app.services import risk_scoring

    org_id = current_user.org_id
    q = _org_filter(db.query(RiskReport), RiskReport, org_id)
    if not include_closed:
        q = q.filter(func.lower(func.coalesce(RiskReport.workflow_status, "")) != "closed")
    rows = q.all()

    counts = [[0] * 5 for _ in range(5)]
    bands = {b: 0 for b in ("Low", "Medium", "High", "Critical")}
    uplift_prevalence = {key: 0 for key, _pts, _label in risk_scoring.UPLIFTS}
    unplotted = 0
    blocks_work = 0
    scores: List[int] = []

    for r in rows:
        if r.blocks_work:
            blocks_work += 1
        band = (r.risk_band or "").strip().title()
        if band in bands:
            bands[band] += 1
        for key, _pts, _label in risk_scoring.UPLIFTS:
            if getattr(r, f"uplift_{key}", 0):
                uplift_prevalence[key] += 1

        row_idx = _risk_axis_index(r.consequence, risk_scoring.SEVERITY)
        col_idx = _risk_axis_index(r.likelihood, risk_scoring.LIKELIHOOD)
        if row_idx is None or col_idx is None:
            # Deliberately "unplotted", not "unscored" — the two are different
            # and the record that proves it exists in this database. A risk can
            # carry a score and a band while still having a consequence word the
            # 5x5 vocabulary does not know ("Serious"), because `_build_row`
            # accepts an explicit `risk_score` and skips the L x S lookup when
            # one is supplied. Calling that unscored would be wrong; dropping it
            # silently would be worse, since a risk missing from the matrix is
            # invisible on it by definition.
            unplotted += 1
            continue
        counts[row_idx][col_idx] += 1
        if r.adjusted_risk_score is not None:
            scores.append(r.adjusted_risk_score)

    plotted = sum(sum(row) for row in counts)
    return {
        "counts": counts,
        # The axis this grid was actually built from, so the client labels the
        # rows and columns with the same vocabulary rather than guessing.
        "severity_axis": _SEVERITY_AXIS,
        "likelihood_axis": _LIKELIHOOD_AXIS,
        "bands": bands,
        "uplift_prevalence": uplift_prevalence,
        "total": len(rows),
        "plotted": plotted,
        "unplotted": unplotted,
        "blocks_work": blocks_work,
        "average_adjusted_score": round(sum(scores) / len(scores), 1) if scores else None,
        "includes_closed": include_closed,
    }


@router.get("/risk-report-summary")
def get_risk_report_summary(
    limit: int = Query(8, le=50),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Headline counts and the worst open risks, for the Risk page's KPI strip.

    "Worst" is the adjusted score, not the raw one: the adjusted score is what
    banded the risk and decided whether work is blocked, so ranking on the raw
    L x S would put a 16 that nobody uplifted above a 12 that three uplifts
    turned into a work stoppage.
    """
    from app.models.risk_report import RiskReport
    from app.services import workflow_stages

    org_id = current_user.org_id
    rows = _org_filter(db.query(RiskReport), RiskReport, org_id).all()

    open_rows = [
        r for r in rows
        if (r.workflow_status or "").strip().lower() != "closed"
    ]

    by_stage = {s.key: 0 for s in workflow_stages.STAGES}
    for r in open_rows:
        key = workflow_stages.stage_for("risk", r.workflow_status)
        if key:
            by_stage[key] += 1

    now = datetime.now()
    overdue = sum(
        1 for r in open_rows
        if r.response_due_at and r.response_due_at < now
    )

    top = sorted(
        (r for r in open_rows if r.adjusted_risk_score is not None),
        key=lambda r: r.adjusted_risk_score,
        reverse=True,
    )[:limit]

    return {
        "total": len(rows),
        "open": len(open_rows),
        "closed": len(rows) - len(open_rows),
        "blocks_work": sum(1 for r in open_rows if r.blocks_work),
        "high_or_critical": sum(
            1 for r in open_rows
            if (r.risk_band or "").strip().title() in ("High", "Critical")
        ),
        "unassessed": sum(1 for r in open_rows if r.adjusted_risk_score is None),
        "overdue": overdue,
        "by_stage": by_stage,
        "top_risks": [
            {
                "id": r.id,
                "reference": f"RIS-{r.id}",
                "title": r.risk_title or (r.description or "")[:80] or None,
                "band": r.risk_band,
                "raw_risk_score": r.raw_risk_score if r.raw_risk_score is not None else r.risk_score,
                "adjusted_risk_score": r.adjusted_risk_score,
                "uplift_total": r.uplift_total or 0,
                "blocks_work": bool(r.blocks_work),
                "workflow_status": r.workflow_status,
                "stage": workflow_stages.stage_for("risk", r.workflow_status),
                "reported_at": r.reported_at.isoformat() if r.reported_at else None,
            }
            for r in top
        ],
    }
