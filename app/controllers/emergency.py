"""WF-15: Emergency Management API Endpoints

Emergency preparedness and response management endpoints for:
- Emergency response plans
- Response teams and ICS structure
- Emergency contact management
- Evacuation procedures
- Emergency drills and exercises
- Emergency equipment inventory
- Real emergency activations
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload

from app.config.database import get_db
from app.core.dependencies import CurrentUser, get_current_user
from app.models.emergency import (
    EmergencyPlan, EmergencyResponseTeam, EmergencyContact,
    EvacuationProcedure, EmergencyDrill, EmergencyEquipment,
    EmergencyActivation
)
from app.utils.logger import get_logger

router = APIRouter(prefix="/emergency", tags=["Emergency Management"])
logger = get_logger(__name__)


# ============================================================================
# Pydantic Schemas
# ============================================================================

class EmergencyPlanCreate(BaseModel):
    plan_name: str
    site_id: int
    emergency_type: str
    scenario_description: Optional[str] = None
    response_objectives: Optional[str] = None
    activation_triggers: Optional[str] = None
    plan_owner_id: Optional[int] = None
    review_frequency: int = 12


class EmergencyDrillCreate(BaseModel):
    drill_name: str
    site_id: int
    emergency_plan_id: Optional[int] = None
    drill_type: str
    emergency_scenario: Optional[str] = None
    scheduled_date: str
    scheduled_time: Optional[str] = None
    drill_coordinator_id: Optional[int] = None
    objectives: Optional[str] = None



class EmergencyActivationCreate(BaseModel):
    site_id: int
    emergency_type: str
    emergency_description: str
    severity_level: str
    occurred_at: str
    location_description: Optional[str] = None
    incident_commander_id: Optional[int] = None


class DrillCompletion(BaseModel):
    overall_rating: int = Field(..., ge=1, le=5)
    objectives_met: bool = True
    participants_actual: Optional[int] = None
    evacuation_time_minutes: Optional[int] = None
    strengths: Optional[str] = None
    weaknesses: Optional[str] = None
    lessons_learned: Optional[str] = None


# ============================================================================
# Emergency Plan Endpoints
# ============================================================================

@router.get("/plans")
def list_emergency_plans(
    site_id: Optional[int] = Query(None),
    emergency_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List all emergency plans."""
    q = db.query(EmergencyPlan).filter(
        EmergencyPlan.organisation_id == current_user.org_id
    )
    
    if site_id:
        q = q.filter(EmergencyPlan.site_id == site_id)
    if emergency_type:
        q = q.filter(EmergencyPlan.emergency_type == emergency_type)
    if status:
        q = q.filter(EmergencyPlan.status == status)
    
    plans = q.all()
    
    return {
        "success": True,
        "data": [
            {
                "id": p.id,
                "plan_name": p.plan_name,
                "plan_number": p.plan_number,
                "emergency_type": p.emergency_type,
                "site_id": p.site_id,
                "status": p.status,
                "version": p.version,
                "next_review_due": p.next_review_due.isoformat() if p.next_review_due else None,
                "last_drill_date": p.last_drill_date.isoformat() if p.last_drill_date else None,
            }
            for p in plans
        ]
    }


@router.post("/plans")
def create_emergency_plan(
    payload: EmergencyPlanCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Create a new emergency plan."""
    # Calculate next review date
    next_review = (datetime.now() + timedelta(days=payload.review_frequency * 30)).date()
    
    plan = EmergencyPlan(
        organisation_id=current_user.org_id,
        site_id=payload.site_id,
        plan_name=payload.plan_name,
        emergency_type=payload.emergency_type,
        scenario_description=payload.scenario_description,
        response_objectives=payload.response_objectives,
        activation_triggers=payload.activation_triggers,
        plan_owner_id=payload.plan_owner_id,
        review_frequency=payload.review_frequency,
        next_review_due=next_review,
        status="draft",
        created_by=current_user.user_id,
    )
    
    db.add(plan)
    db.commit()
    db.refresh(plan)
    
    logger.info(f"Emergency plan created: {plan.plan_name} by user {current_user.user_id}")
    
    return {"success": True, "data": {"id": plan.id}, "message": "Emergency plan created"}



# ============================================================================
# Emergency Drill Endpoints
# ============================================================================

@router.get("/drills")
def list_emergency_drills(
    site_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    upcoming_only: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List emergency drills."""
    q = db.query(EmergencyDrill).filter(
        EmergencyDrill.organisation_id == current_user.org_id
    )
    
    if site_id:
        q = q.filter(EmergencyDrill.site_id == site_id)
    if status:
        q = q.filter(EmergencyDrill.status == status)
    if upcoming_only:
        q = q.filter(EmergencyDrill.scheduled_date >= datetime.now().date())
    
    drills = q.order_by(EmergencyDrill.scheduled_date.desc()).all()
    
    return {
        "success": True,
        "data": [
            {
                "id": d.id,
                "drill_name": d.drill_name,
                "drill_type": d.drill_type,
                "emergency_scenario": d.emergency_scenario,
                "scheduled_date": d.scheduled_date.isoformat() if d.scheduled_date else None,
                "actual_date": d.actual_date.isoformat() if d.actual_date else None,
                "status": d.status,
                "overall_rating": d.overall_rating,
                "objectives_met": d.objectives_met,
                "participants_actual": d.participants_actual,
            }
            for d in drills
        ]
    }


@router.post("/drills")
def create_emergency_drill(
    payload: EmergencyDrillCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Schedule a new emergency drill."""
    drill = EmergencyDrill(
        organisation_id=current_user.org_id,
        site_id=payload.site_id,
        emergency_plan_id=payload.emergency_plan_id,
        drill_name=payload.drill_name,
        drill_type=payload.drill_type,
        emergency_scenario=payload.emergency_scenario,
        scheduled_date=datetime.strptime(payload.scheduled_date, "%Y-%m-%d").date(),
        scheduled_time=datetime.strptime(payload.scheduled_time, "%H:%M").time() if payload.scheduled_time else None,
        drill_coordinator_id=payload.drill_coordinator_id,
        objectives=payload.objectives,
        status="scheduled",
        created_by=current_user.user_id,
    )
    
    db.add(drill)
    db.commit()
    db.refresh(drill)
    
    return {"success": True, "data": {"id": drill.id}, "message": "Emergency drill scheduled"}


@router.post("/drills/{drill_id}/complete")
def complete_drill(
    drill_id: int,
    payload: DrillCompletion,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Mark drill as completed and record results."""
    drill = db.query(EmergencyDrill).filter(
        and_(
            EmergencyDrill.id == drill_id,
            EmergencyDrill.organisation_id == current_user.org_id
        )
    ).first()

    if not drill:
        raise HTTPException(status_code=404, detail="Drill not found")

    drill.status = "completed"
    drill.actual_date = datetime.now().date()
    drill.actual_time = datetime.now().time()
    drill.overall_rating = payload.overall_rating
    drill.objectives_met = payload.objectives_met
    drill.participants_actual = payload.participants_actual
    drill.evacuation_time_minutes = payload.evacuation_time_minutes
    drill.strengths_identified = payload.strengths
    drill.weaknesses_identified = payload.weaknesses
    drill.lessons_learned = payload.lessons_learned

    # Update plan's last drill date
    if drill.emergency_plan_id:
        plan = db.query(EmergencyPlan).filter(EmergencyPlan.id == drill.emergency_plan_id).first()
        if plan:
            plan.last_drill_date = drill.actual_date

    db.commit()

    logger.info(f"Drill completed: {drill.drill_name} - Rating: {payload.overall_rating}/5")
    
    return {"success": True, "message": "Drill results recorded"}



# ============================================================================
# Emergency Equipment Endpoints
# ============================================================================

@router.get("/equipment")
def list_emergency_equipment(
    site_id: Optional[int] = Query(None),
    equipment_type: Optional[str] = Query(None),
    expired: bool = Query(False),
    inspection_due: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List emergency equipment inventory."""
    q = db.query(EmergencyEquipment).filter(
        EmergencyEquipment.organisation_id == current_user.org_id
    )
    
    if site_id:
        q = q.filter(EmergencyEquipment.site_id == site_id)
    if equipment_type:
        q = q.filter(EmergencyEquipment.equipment_type == equipment_type)
    if expired:
        q = q.filter(EmergencyEquipment.expiry_date < datetime.now().date())
    if inspection_due:
        q = q.filter(EmergencyEquipment.next_inspection_due <= datetime.now().date())
    
    equipment_list = q.order_by(EmergencyEquipment.next_inspection_due).all()
    
    return {
        "success": True,
        "data": [
            {
                "id": eq.id,
                "equipment_name": eq.equipment_name,
                "equipment_type": eq.equipment_type,
                "asset_tag": eq.asset_tag,
                "building": eq.building,
                "floor_level": eq.floor_level,
                "equipment_status": eq.equipment_status,
                "expiry_date": eq.expiry_date.isoformat() if eq.expiry_date else None,
                "next_inspection_due": eq.next_inspection_due.isoformat() if eq.next_inspection_due else None,
            }
            for eq in equipment_list
        ]
    }


# ============================================================================
# Emergency Activation Endpoints (Real Emergencies)
# ============================================================================

@router.get("/activations")
def list_emergency_activations(
    site_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List real emergency activations."""
    q = db.query(EmergencyActivation).filter(
        EmergencyActivation.organisation_id == current_user.org_id
    )
    
    if site_id:
        q = q.filter(EmergencyActivation.site_id == site_id)
    if status:
        q = q.filter(EmergencyActivation.status == status)
    if start_date:
        q = q.filter(EmergencyActivation.occurred_at >= datetime.strptime(start_date, "%Y-%m-%d"))
    if end_date:
        q = q.filter(EmergencyActivation.occurred_at <= datetime.strptime(end_date, "%Y-%m-%d"))
    
    activations = q.order_by(EmergencyActivation.occurred_at.desc()).all()
    
    return {
        "success": True,
        "data": [
            {
                "id": a.id,
                "emergency_type": a.emergency_type,
                "emergency_description": a.emergency_description,
                "severity_level": a.severity_level,
                "occurred_at": a.occurred_at.isoformat() if a.occurred_at else None,
                "status": a.status,
                "evacuated": a.evacuated,
                "people_evacuated": a.people_evacuated,
                "injuries": a.injuries,
                "fatalities": a.fatalities,
                "response_time_minutes": a.response_time_minutes,
            }
            for a in activations
        ]
    }


@router.post("/activations")
def create_emergency_activation(
    payload: EmergencyActivationCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Log a real emergency activation."""
    activation = EmergencyActivation(
        organisation_id=current_user.org_id,
        site_id=payload.site_id,
        emergency_type=payload.emergency_type,
        emergency_description=payload.emergency_description,
        severity_level=payload.severity_level,
        occurred_at=datetime.strptime(payload.occurred_at, "%Y-%m-%d %H:%M:%S"),
        detected_at=datetime.now(),
        reported_at=datetime.now(),
        location_description=payload.location_description,
        incident_commander_id=payload.incident_commander_id,
        status="active",
        reported_by=current_user.user_id,
    )
    
    db.add(activation)
    db.commit()
    db.refresh(activation)
    
    logger.warning(
        f"EMERGENCY ACTIVATED: {activation.emergency_type} at site {payload.site_id} - Severity: {payload.severity_level}"
    )
    
    return {"success": True, "data": {"id": activation.id}, "message": "Emergency activation logged"}



# ============================================================================
# Dashboard & Analytics
# ============================================================================

@router.get("/dashboard")
def get_emergency_dashboard(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get emergency management dashboard metrics."""
    
    # Emergency plans
    total_plans = db.query(func.count(EmergencyPlan.id)).filter(
        EmergencyPlan.organisation_id == current_user.org_id
    ).scalar()
    
    approved_plans = db.query(func.count(EmergencyPlan.id)).filter(
        and_(
            EmergencyPlan.organisation_id == current_user.org_id,
            EmergencyPlan.status == "approved"
        )
    ).scalar()
    
    # Drills
    total_drills = db.query(func.count(EmergencyDrill.id)).filter(
        EmergencyDrill.organisation_id == current_user.org_id
    ).scalar()
    
    upcoming_drills = db.query(func.count(EmergencyDrill.id)).filter(
        and_(
            EmergencyDrill.organisation_id == current_user.org_id,
            EmergencyDrill.scheduled_date >= datetime.now().date(),
            EmergencyDrill.status == "scheduled"
        )
    ).scalar()
    
    # Equipment
    total_equipment = db.query(func.count(EmergencyEquipment.id)).filter(
        EmergencyEquipment.organisation_id == current_user.org_id
    ).scalar()
    
    expired_equipment = db.query(func.count(EmergencyEquipment.id)).filter(
        and_(
            EmergencyEquipment.organisation_id == current_user.org_id,
            EmergencyEquipment.expiry_date < datetime.now().date()
        )
    ).scalar()
    
    inspection_due = db.query(func.count(EmergencyEquipment.id)).filter(
        and_(
            EmergencyEquipment.organisation_id == current_user.org_id,
            EmergencyEquipment.next_inspection_due <= datetime.now().date()
        )
    ).scalar()
    
    # Real emergencies (last 12 months)
    one_year_ago = datetime.now() - timedelta(days=365)
    emergencies_ytd = db.query(func.count(EmergencyActivation.id)).filter(
        and_(
            EmergencyActivation.organisation_id == current_user.org_id,
            EmergencyActivation.occurred_at >= one_year_ago
        )
    ).scalar()
    
    # Response teams
    active_teams = db.query(func.count(EmergencyResponseTeam.id)).filter(
        and_(
            EmergencyResponseTeam.organisation_id == current_user.org_id,
            EmergencyResponseTeam.status == "active"
        )
    ).scalar()
    
    # Emergency contacts
    verified_contacts = db.query(func.count(EmergencyContact.id)).filter(
        and_(
            EmergencyContact.organisation_id == current_user.org_id,
            EmergencyContact.status == "active"
        )
    ).scalar()
    
    # Drill performance trend (last 5 completed drills)
    recent_drills = db.query(EmergencyDrill).filter(
        and_(
            EmergencyDrill.organisation_id == current_user.org_id,
            EmergencyDrill.status == "completed"
        )
    ).order_by(EmergencyDrill.actual_date.desc()).limit(5).all()
    
    drill_ratings = [
        {"date": d.actual_date.isoformat(), "rating": d.overall_rating or 0}
        for d in recent_drills if d.actual_date
    ]
    
    avg_drill_rating = sum(d.overall_rating for d in recent_drills if d.overall_rating) / len(recent_drills) if recent_drills else 0
    
    return {
        "success": True,
        "data": {
            "summary": {
                "total_emergency_plans": total_plans,
                "approved_plans": approved_plans,
                "plan_approval_rate": round((approved_plans / total_plans * 100), 1) if total_plans > 0 else 0,
                "total_drills": total_drills,
                "upcoming_drills": upcoming_drills,
                "avg_drill_rating": round(avg_drill_rating, 1),
                "total_equipment": total_equipment,
                "expired_equipment": expired_equipment,
                "inspection_due": inspection_due,
                "emergencies_ytd": emergencies_ytd,
                "active_response_teams": active_teams,
                "verified_contacts": verified_contacts,
            },
            "drill_performance_trend": drill_ratings,
        }
    }
