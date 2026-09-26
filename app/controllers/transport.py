"""WF-09 · Transport & Logistics.

    worker      POST /journey-plans                 route x mode x cargo -> JRS
    worker      POST /journey-plans/{id}/pre-trip   vehicle QR scan + defect check
    worker      POST /journey-plans/{id}/depart     runs the departure gates
    worker      POST /journey-plans/{id}/check-in   timed, GPS, defects, deviations
    supervisor  POST /journey-plans/{id}/authorise  required when JRS >= 13
    supervisor  GET  /journey-plans/monitor         live board, missed check-ins
    manager     GET  /journey-plans/kpis            monthly transport KPI batch
    auditor     GET  /journey-plans/audit-list      pre-trip sampling, log completeness
    any         GET  /vehicles, /vehicles/by-qr/{code}

Check-in cadence: road every 2 h, marine per voyage plan, air per flight plan.
A missed check-in escalates to the control room.
"""
from datetime import date, datetime, timedelta
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
from app.models.transport import CheckInEvent, JourneyPlan, Vehicle, WeatherLimitTable
from app.schemas.gates import GateEvaluationOut
from app.schemas.transport import (
    CheckInCreate,
    CheckInMonitorRow,
    CheckInResponse,
    JourneyAuthorise,
    JourneyPlanCreate,
    JourneyPlanResponse,
    PreTripCheck,
    TransportKpiResponse,
    VehicleCreate,
    VehicleInspection,
    VehicleResponse,
    WeatherLimitCreate,
)
from app.services.gate_engine import evaluate_journey_gates
from app.services.hse_formulae import journey_risk_score

router = APIRouter(prefix="/journey-plans", tags=["Transport & Logistics"])
vehicles_router = APIRouter(prefix="/vehicles", tags=["Transport & Logistics"])

MONITOR_ROLES = SUPERVISOR_ROLES | MANAGER_ROLES | AUDITOR_ROLES


def _get_journey(db: Session, journey_id: int, org_id: Optional[int]) -> JourneyPlan:
    row = (
        db.query(JourneyPlan)
        .filter(JourneyPlan.id == journey_id)
        .filter(JourneyPlan.organisation_id == org_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Journey plan not found")
    return row


# ══════════════════════════════════════════════════════════════════════════════
# VEHICLES
# ══════════════════════════════════════════════════════════════════════════════
@vehicles_router.get("", response_model=List[VehicleResponse])
@vehicles_router.get("/", response_model=List[VehicleResponse])
def list_vehicles(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    rows = (
        db.query(Vehicle)
        .filter(Vehicle.organisation_id == current_user.org_id)
        .filter(Vehicle.active == 1)
        .all()
    )
    return [VehicleResponse.model_validate(r) for r in rows]


@vehicles_router.post("", response_model=VehicleResponse, status_code=201)
@vehicles_router.post("/", response_model=VehicleResponse, status_code=201)
def create_vehicle(
    payload: VehicleCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, MANAGER_ROLES, "add a vehicle")
    row = Vehicle(
        organisation_id=current_user.org_id,
        source_system="mobile",
        **payload.model_dump(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return VehicleResponse.model_validate(row)


@vehicles_router.get("/by-qr/{qr_code}", response_model=VehicleResponse)
def vehicle_by_qr(
    qr_code: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Vehicle QR scan at the pre-trip gate."""
    row = (
        db.query(Vehicle)
        .filter(Vehicle.qr_code == qr_code)
        .filter(Vehicle.organisation_id == current_user.org_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="No vehicle matches that code")
    return VehicleResponse.model_validate(row)


@vehicles_router.post("/{vehicle_id}/inspect", response_model=VehicleResponse)
def inspect_vehicle(
    vehicle_id: int,
    payload: VehicleInspection,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    row = (
        db.query(Vehicle)
        .filter(Vehicle.id == vehicle_id)
        .filter(Vehicle.organisation_id == current_user.org_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    row.defect_status = payload.defect_status
    row.defect_notes = payload.defect_notes
    row.last_inspection_at = datetime.now()
    row.last_verified_at = datetime.now()
    db.commit()
    db.refresh(row)
    return VehicleResponse.model_validate(row)


@vehicles_router.post("/weather-limits", status_code=201)
def create_weather_limit(
    payload: WeatherLimitCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, MANAGER_ROLES, "set weather operating limits")
    row = WeatherLimitTable(
        organisation_id=current_user.org_id,
        source_system="web",
        **payload.model_dump(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "transport_mode": row.transport_mode}


# ══════════════════════════════════════════════════════════════════════════════
# JOURNEY PLANS
# ══════════════════════════════════════════════════════════════════════════════
@router.post("", response_model=JourneyPlanResponse, status_code=201)
@router.post("/", response_model=JourneyPlanResponse, status_code=201)
def create_journey(
    payload: JourneyPlanCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    emp_id = employee_id_for(db, current_user.user_id)
    if not emp_id:
        raise HTTPException(status_code=400, detail="No employee record linked to this user")

    jrs = journey_risk_score(
        payload.route_score, payload.mode_score, payload.cargo_score, payload.transport_mode
    )

    row = JourneyPlan(
        organisation_id=current_user.org_id,
        employee_id=emp_id,
        vehicle_id=payload.vehicle_id,
        origin=payload.origin,
        destination=payload.destination,
        transport_mode=payload.transport_mode,
        route_score=payload.route_score,
        mode_score=payload.mode_score,
        cargo_score=payload.cargo_score,
        journey_risk_score=jrs.journey_risk_score,
        risk_band=jrs.risk_band,
        requires_authorisation=1 if jrs.requires_authorisation else 0,
        # A high-risk journey cannot simply be a draft the driver self-approves.
        status="pending_authorisation" if jrs.requires_authorisation else "draft",
        planned_departure=payload.planned_departure,
        planned_arrival=payload.planned_arrival,
        checkin_interval_minutes=jrs.checkin_interval_minutes,
        comms_protocol=payload.comms_protocol,
        weather_snapshot=payload.weather,
        source_system="mobile",
        last_verified_at=datetime.now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return JourneyPlanResponse.model_validate(row)


@router.get("/mine", response_model=List[JourneyPlanResponse])
def my_journeys(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    emp_id = employee_id_for(db, current_user.user_id)
    rows = (
        db.query(JourneyPlan)
        .filter(JourneyPlan.employee_id == emp_id)
        .order_by(JourneyPlan.id.desc())
        .limit(50)
        .all()
    )
    return [JourneyPlanResponse.model_validate(r) for r in rows]


@router.get("/pending-authorisation", response_model=List[JourneyPlanResponse])
def pending_authorisation(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, MONITOR_ROLES, "view journeys awaiting authorisation")
    rows = (
        db.query(JourneyPlan)
        .filter(JourneyPlan.organisation_id == current_user.org_id)
        .filter(JourneyPlan.status == "pending_authorisation")
        .order_by(JourneyPlan.journey_risk_score.desc())
        .all()
    )
    return [JourneyPlanResponse.model_validate(r) for r in rows]


@router.post("/{journey_id}/authorise", response_model=JourneyPlanResponse)
def authorise(
    journey_id: int,
    payload: JourneyAuthorise,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Approve movements scoring >= 13. Sets check-in interval and comms protocol."""
    require_role(current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES, "authorise a journey")
    row = _get_journey(db, journey_id, current_user.org_id)

    if payload.approved:
        row.status = "authorised"
        row.authorised_by = employee_id_for(db, current_user.user_id)
        row.authorised_at = datetime.now()
        if payload.checkin_interval_minutes:
            row.checkin_interval_minutes = payload.checkin_interval_minutes
        if payload.comms_protocol:
            row.comms_protocol = payload.comms_protocol
    else:
        row.status = "rejected"
        row.rejection_reason = payload.rejection_reason

    db.commit()
    db.refresh(row)
    return JourneyPlanResponse.model_validate(row)


@router.post("/{journey_id}/pre-trip", response_model=JourneyPlanResponse)
def pre_trip(
    journey_id: int,
    payload: PreTripCheck,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Pre-trip gate: vehicle QR scan and defect check."""
    row = _get_journey(db, journey_id, current_user.org_id)

    if payload.vehicle_id:
        row.vehicle_id = payload.vehicle_id
    if row.vehicle_id:
        v = db.query(Vehicle).filter(Vehicle.id == row.vehicle_id).first()
        if v:
            v.defect_status = payload.defect_status
            v.defect_notes = payload.defects
            v.last_inspection_at = datetime.now()

    row.pretrip_completed_at = datetime.now()
    row.pretrip_defects = payload.defects
    db.commit()
    db.refresh(row)
    return JourneyPlanResponse.model_validate(row)


@router.post("/{journey_id}/depart", response_model=GateEvaluationOut)
def depart(
    journey_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Run the departure gates. Blocks leave the journey where it is.

    Departure is a gate point, not a formality — competence, fatigue and the
    weather/authorisation gate all run here, and a blocked verdict does not
    move the journey to in_progress.
    """
    row = _get_journey(db, journey_id, current_user.org_id)

    if row.requires_authorisation and row.authorised_at is None:
        raise HTTPException(
            status_code=403,
            detail=f"Journey risk {row.journey_risk_score} requires Transport Authorisation first",
        )

    # A grounded or majorly defective vehicle cannot depart.
    if row.vehicle_id:
        v = db.query(Vehicle).filter(Vehicle.id == row.vehicle_id).first()
        if v and v.defect_status in ("major", "grounded"):
            raise HTTPException(
                status_code=403,
                detail=f"Vehicle {v.registration} is {v.defect_status} — departure blocked",
            )

    evaluation = evaluate_journey_gates(
        db,
        current_user.org_id,
        row,
        evaluated_by=employee_id_for(db, current_user.user_id),
    )

    if evaluation.overall != "block":
        row.status = "in_progress"
        row.actual_departure = datetime.now()

        # Lay down the timed check-in schedule the monitor watches.
        interval = row.checkin_interval_minutes or 120
        start = row.actual_departure
        eta = row.planned_arrival or (start + timedelta(hours=8))
        seq, due = 1, start + timedelta(minutes=interval)
        while due <= eta and seq <= 48:
            db.add(
                CheckInEvent(
                    organisation_id=current_user.org_id,
                    journey_plan_id=row.id,
                    sequence_no=seq,
                    due_at=due,
                    source_system="server",
                )
            )
            seq += 1
            due += timedelta(minutes=interval)

        db.commit()

    return GateEvaluationOut(**evaluation.to_dict())


@router.post("/{journey_id}/check-in", response_model=CheckInResponse)
def check_in(
    journey_id: int,
    payload: CheckInCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Timed check-in. Fills the earliest outstanding slot."""
    row = _get_journey(db, journey_id, current_user.org_id)

    event = (
        db.query(CheckInEvent)
        .filter(CheckInEvent.journey_plan_id == row.id)
        .filter(CheckInEvent.checked_in_at.is_(None))
        .order_by(CheckInEvent.due_at.asc())
        .first()
    )
    if event is None:
        # Unscheduled check-in (early arrival, ad-hoc report) — still recorded.
        last = (
            db.query(CheckInEvent)
            .filter(CheckInEvent.journey_plan_id == row.id)
            .order_by(CheckInEvent.sequence_no.desc())
            .first()
        )
        event = CheckInEvent(
            organisation_id=current_user.org_id,
            journey_plan_id=row.id,
            sequence_no=(last.sequence_no + 1) if last else 1,
            due_at=datetime.now(),
            source_system="mobile",
        )
        db.add(event)

    now = datetime.now()
    event.checked_in_at = now
    event.missed = 1 if event.due_at and now > event.due_at + timedelta(minutes=15) else 0
    event.gps_latitude = payload.gps_latitude
    event.gps_longitude = payload.gps_longitude
    event.defects_reported = payload.defects_reported
    event.deviations = payload.deviations
    event.notes = payload.notes
    db.commit()
    db.refresh(event)
    return CheckInResponse.model_validate(event)


@router.post("/{journey_id}/arrive", response_model=JourneyPlanResponse)
def arrive(
    journey_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    row = _get_journey(db, journey_id, current_user.org_id)
    row.status = "completed"
    row.actual_arrival = datetime.now()
    db.commit()
    db.refresh(row)
    return JourneyPlanResponse.model_validate(row)


@router.get("/{journey_id}/check-ins", response_model=List[CheckInResponse])
def journey_check_ins(
    journey_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    _get_journey(db, journey_id, current_user.org_id)
    rows = (
        db.query(CheckInEvent)
        .filter(CheckInEvent.journey_plan_id == journey_id)
        .order_by(CheckInEvent.sequence_no)
        .all()
    )
    return [CheckInResponse.model_validate(r) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# SUPERVISOR — live check-in monitor
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/monitor", response_model=List[CheckInMonitorRow])
def check_in_monitor(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Live journey board — who is overdue, and by how long."""
    require_role(current_user.role, MONITOR_ROLES, "view the check-in monitor")
    now = datetime.now()

    journeys = (
        db.query(JourneyPlan)
        .filter(JourneyPlan.organisation_id == current_user.org_id)
        .filter(JourneyPlan.status == "in_progress")
        .all()
    )

    out: List[CheckInMonitorRow] = []
    for j in journeys:
        events = (
            db.query(CheckInEvent)
            .filter(CheckInEvent.journey_plan_id == j.id)
            .order_by(CheckInEvent.due_at)
            .all()
        )
        outstanding = [e for e in events if e.checked_in_at is None]
        next_due = outstanding[0].due_at if outstanding else None
        overdue_min = int((now - next_due).total_seconds() // 60) if next_due and now > next_due else None

        emp = db.execute(
            text("SELECT full_name FROM employees WHERE id = :i"), {"i": j.employee_id}
        ).mappings().first()

        # Escalate anything more than one interval past due.
        if overdue_min and overdue_min > (j.checkin_interval_minutes or 120):
            for e in outstanding:
                if e.due_at < now and not e.escalated_at:
                    e.missed = 1
                    e.escalated_at = now
            db.commit()

        out.append(
            CheckInMonitorRow(
                journey_plan_id=j.id,
                employee_id=j.employee_id,
                employee_name=emp["full_name"] if emp else None,
                destination=j.destination,
                risk_band=j.risk_band,
                status=j.status,
                next_due_at=next_due,
                minutes_overdue=overdue_min,
                missed_count=sum(1 for e in events if e.missed),
                is_escalated=any(e.escalated_at for e in events),
            )
        )

    out.sort(key=lambda r: (r.minutes_overdue or -1), reverse=True)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# MANAGER / AUDITOR
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/kpis", response_model=TransportKpiResponse)
def transport_kpis(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Monthly KPI batch — weather limits by mode, fatigue flag rate, defect rate."""
    require_role(current_user.role, MONITOR_ROLES, "view transport KPIs")
    since = datetime.now() - timedelta(days=days)

    journeys = (
        db.query(JourneyPlan)
        .filter(JourneyPlan.organisation_id == current_user.org_id)
        .filter(JourneyPlan.created_at >= since)
        .all()
    )
    high = [j for j in journeys if j.risk_band == "high"]
    authorised = [j for j in high if j.authorised_at]

    events = (
        db.query(CheckInEvent)
        .filter(CheckInEvent.organisation_id == current_user.org_id)
        .filter(CheckInEvent.due_at >= since)
        .all()
    )
    missed = [e for e in events if e.missed]

    defect_vehicles = (
        db.query(Vehicle)
        .filter(Vehicle.organisation_id == current_user.org_id)
        .filter(Vehicle.defect_status.in_(["minor", "major", "grounded"]))
        .count()
    )

    declarations = (
        db.query(FatigueDeclaration)
        .filter(FatigueDeclaration.organisation_id == current_user.org_id)
        .filter(FatigueDeclaration.declared_at >= since)
        .all()
    )
    flagged = [d for d in declarations if d.band != "acceptable"]

    by_mode: dict = {}
    for j in journeys:
        by_mode[j.transport_mode] = by_mode.get(j.transport_mode, 0) + 1

    return TransportKpiResponse(
        period_days=days,
        journeys_total=len(journeys),
        journeys_high_risk=len(high),
        authorisation_rate=round(len(authorised) / len(high) * 100, 2) if high else 100.0,
        checkins_due=len(events),
        checkins_missed=len(missed),
        checkin_completeness=(
            round((len(events) - len(missed)) / len(events) * 100, 2) if events else 100.0
        ),
        vehicles_with_defects=defect_vehicles,
        fatigue_flag_rate=(
            round(len(flagged) / len(declarations) * 100, 2) if declarations else 0.0
        ),
        by_mode=by_mode,
    )


@router.get("/audit-list", response_model=List[JourneyPlanResponse])
def audit_list(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Pre-trip inspection sampling and check-in log completeness."""
    require_role(current_user.role, AUDITOR_ROLES | MANAGER_ROLES, "audit journey plans")
    rows = (
        db.query(JourneyPlan)
        .filter(JourneyPlan.organisation_id == current_user.org_id)
        .filter(JourneyPlan.created_at >= datetime.now() - timedelta(days=days))
        .order_by(JourneyPlan.journey_risk_score.desc())
        .all()
    )
    return [JourneyPlanResponse.model_validate(r) for r in rows]
