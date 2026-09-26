"""WF-14: Process Safety Management (PSM) API Endpoints

PSM program management endpoints for:
- PSM element compliance tracking
- Process Hazard Analysis (PHA) lifecycle
- Mechanical Integrity (MI) program
- Operating procedures management
- PSM compliance audits
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload

from app.config.database import get_db
from app.core.dependencies import CurrentUser, get_current_user
from app.models.psm import (
    PSMElement, PHAStudy, PHAScenario, PHARecommendation,
    CriticalEquipment, EquipmentInspection, OperatingProcedure,
    PSMAudit, PSMAuditFinding
)
from app.utils.logger import get_logger

router = APIRouter(prefix="/psm", tags=["Process Safety Management"])
logger = get_logger(__name__)


# ============================================================================
# Pydantic Schemas
# ============================================================================

class PSMElementCreate(BaseModel):
    element_name: str
    element_code: Optional[str] = None
    element_category: Optional[str] = None
    regulatory_requirement: Optional[str] = None
    site_id: Optional[int] = None
    element_owner_id: Optional[int] = None


class PHAStudyCreate(BaseModel):
    study_name: str
    study_number: Optional[str] = None
    site_id: int
    process_unit: Optional[str] = None
    process_description: Optional[str] = None
    pha_method: str
    study_scope: Optional[str] = None
    planned_start_date: Optional[str] = None
    planned_completion_date: Optional[str] = None
    team_leader_id: Optional[int] = None
    revalidation_years: int = 5



class PHAScenarioCreate(BaseModel):
    pha_study_id: int
    node_number: Optional[str] = None
    scenario_number: Optional[str] = None
    deviation: Optional[str] = None
    cause: Optional[str] = None
    consequence: Optional[str] = None
    likelihood_before: Optional[int] = Field(None, ge=1, le=5)
    severity_before: Optional[int] = Field(None, ge=1, le=5)
    safeguards: Optional[str] = None
    likelihood_after: Optional[int] = Field(None, ge=1, le=5)
    severity_after: Optional[int] = Field(None, ge=1, le=5)


class CriticalEquipmentCreate(BaseModel):
    equipment_tag: str
    equipment_name: str
    site_id: int
    equipment_type: Optional[str] = None
    process_unit: Optional[str] = None
    is_safety_critical: bool = False
    inspection_frequency: Optional[int] = None
    testing_frequency: Optional[int] = None
    owner_id: Optional[int] = None


# ============================================================================
# PSM Element Endpoints
# ============================================================================

@router.get("/elements")
def list_psm_elements(
    site_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List all PSM elements for organization."""
    q = db.query(PSMElement).filter(
        PSMElement.organisation_id == current_user.org_id
    )
    
    if site_id:
        q = q.filter(PSMElement.site_id == site_id)
    if status:
        q = q.filter(PSMElement.status == status)
    
    elements = q.all()
    
    return {
        "success": True,
        "data": [
            {
                "id": e.id,
                "element_name": e.element_name,
                "element_code": e.element_code,
                "status": e.status,
                "compliance_level": e.compliance_level,
                "implementation_date": e.implementation_date.isoformat() if e.implementation_date else None,
                "next_audit_due": e.next_audit_due.isoformat() if e.next_audit_due else None,
                "open_actions": e.open_actions,
            }
            for e in elements
        ]
    }


@router.post("/elements")
def create_psm_element(
    payload: PSMElementCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Create a new PSM element."""
    element = PSMElement(
        organisation_id=current_user.org_id,
        element_name=payload.element_name,
        element_code=payload.element_code,
        element_category=payload.element_category,
        regulatory_requirement=payload.regulatory_requirement,
        site_id=payload.site_id,
        element_owner_id=payload.element_owner_id,
        status="not_started",
        created_by=current_user.user_id,
    )
    
    db.add(element)
    db.commit()
    db.refresh(element)
    
    return {"success": True, "data": {"id": element.id}, "message": "PSM element created"}



# ============================================================================
# PHA Study Endpoints
# ============================================================================

@router.get("/pha-studies")
def list_pha_studies(
    site_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    overdue_revalidation: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List all PHA studies."""
    q = db.query(PHAStudy).filter(
        PHAStudy.organisation_id == current_user.org_id
    )
    
    if site_id:
        q = q.filter(PHAStudy.site_id == site_id)
    if status:
        q = q.filter(PHAStudy.status == status)
    if overdue_revalidation:
        q = q.filter(PHAStudy.next_revalidation_due < datetime.now().date())
    
    studies = q.order_by(PHAStudy.next_revalidation_due).all()
    
    return {
        "success": True,
        "data": [
            {
                "id": s.id,
                "study_name": s.study_name,
                "study_number": s.study_number,
                "site_id": s.site_id,
                "process_unit": s.process_unit,
                "pha_method": s.pha_method,
                "status": s.status,
                "scenarios_analyzed": s.scenarios_analyzed,
                "recommendations_total": s.recommendations_total,
                "recommendations_open": s.recommendations_open,
                "next_revalidation_due": s.next_revalidation_due.isoformat() if s.next_revalidation_due else None,
            }
            for s in studies
        ]
    }


@router.post("/pha-studies")
def create_pha_study(
    payload: PHAStudyCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Create a new PHA study."""
    # Calculate revalidation date
    next_revalidation = None
    if payload.planned_completion_date:
        completion = datetime.strptime(payload.planned_completion_date, "%Y-%m-%d")
        next_revalidation = (completion + timedelta(days=payload.revalidation_years * 365)).date()
    
    study = PHAStudy(
        organisation_id=current_user.org_id,
        site_id=payload.site_id,
        study_name=payload.study_name,
        study_number=payload.study_number,
        process_unit=payload.process_unit,
        process_description=payload.process_description,
        pha_method=payload.pha_method,
        study_scope=payload.study_scope,
        planned_start_date=datetime.strptime(payload.planned_start_date, "%Y-%m-%d").date() if payload.planned_start_date else None,
        planned_completion_date=datetime.strptime(payload.planned_completion_date, "%Y-%m-%d").date() if payload.planned_completion_date else None,
        team_leader_id=payload.team_leader_id,
        revalidation_years=payload.revalidation_years,
        next_revalidation_due=next_revalidation,
        status="planned",
        created_by=current_user.user_id,
    )
    
    db.add(study)
    db.commit()
    db.refresh(study)
    
    logger.info(f"PHA study created: {study.study_name} by user {current_user.user_id}")
    
    return {"success": True, "data": {"id": study.id}, "message": "PHA study created"}


@router.post("/pha-studies/{study_id}/scenarios")
def add_pha_scenario(
    study_id: int,
    payload: PHAScenarioCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Add a hazard scenario to PHA study."""
    study = db.query(PHAStudy).filter(
        and_(
            PHAStudy.id == study_id,
            PHAStudy.organisation_id == current_user.org_id
        )
    ).first()
    
    if not study:
        raise HTTPException(status_code=404, detail="PHA study not found")
    
    # Calculate risk scores
    risk_before = (payload.likelihood_before * payload.severity_before) if payload.likelihood_before and payload.severity_before else None
    risk_after = (payload.likelihood_after * payload.severity_after) if payload.likelihood_after and payload.severity_after else None
    
    scenario = PHAScenario(
        pha_study_id=study_id,
        node_number=payload.node_number,
        scenario_number=payload.scenario_number,
        deviation=payload.deviation,
        cause=payload.cause,
        consequence=payload.consequence,
        likelihood_before=payload.likelihood_before,
        severity_before=payload.severity_before,
        risk_score_before=risk_before,
        safeguards=payload.safeguards,
        likelihood_after=payload.likelihood_after,
        severity_after=payload.severity_after,
        risk_score_after=risk_after,
        risk_acceptable=(risk_after <= 6) if risk_after else False,
        requires_action=(risk_after > 6) if risk_after else True,
    )
    
    db.add(scenario)
    
    # Update study counters
    study.scenarios_analyzed = (study.scenarios_analyzed or 0) + 1
    if risk_after and risk_after >= 15:
        study.high_risk_scenarios = (study.high_risk_scenarios or 0) + 1
    
    db.commit()
    db.refresh(scenario)
    
    return {"success": True, "data": {"id": scenario.id}, "message": "PHA scenario added"}



# ============================================================================
# Mechanical Integrity Endpoints
# ============================================================================

@router.get("/equipment")
def list_critical_equipment(
    site_id: Optional[int] = Query(None),
    safety_critical_only: bool = Query(False),
    inspection_due: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List critical equipment."""
    q = db.query(CriticalEquipment).filter(
        CriticalEquipment.organisation_id == current_user.org_id
    )
    
    if site_id:
        q = q.filter(CriticalEquipment.site_id == site_id)
    if safety_critical_only:
        q = q.filter(CriticalEquipment.is_safety_critical == True)
    if inspection_due:
        q = q.filter(CriticalEquipment.next_inspection_due <= datetime.now().date())
    
    equipment_list = q.order_by(CriticalEquipment.next_inspection_due).all()
    
    return {
        "success": True,
        "data": [
            {
                "id": eq.id,
                "equipment_tag": eq.equipment_tag,
                "equipment_name": eq.equipment_name,
                "equipment_type": eq.equipment_type,
                "is_safety_critical": eq.is_safety_critical,
                "equipment_status": eq.equipment_status,
                "condition_rating": eq.condition_rating,
                "next_inspection_due": eq.next_inspection_due.isoformat() if eq.next_inspection_due else None,
                "deficiencies_open": eq.deficiencies_open,
            }
            for eq in equipment_list
        ]
    }


@router.post("/equipment")
def create_critical_equipment(
    payload: CriticalEquipmentCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Register critical equipment."""
    # Check if tag already exists
    existing = db.query(CriticalEquipment).filter(
        and_(
            CriticalEquipment.equipment_tag == payload.equipment_tag,
            CriticalEquipment.organisation_id == current_user.org_id
        )
    ).first()
    
    if existing:
        raise HTTPException(status_code=409, detail="Equipment tag already exists")
    
    # Calculate next inspection date
    next_inspection = None
    if payload.inspection_frequency:
        next_inspection = (datetime.now() + timedelta(days=payload.inspection_frequency)).date()
    
    equipment = CriticalEquipment(
        organisation_id=current_user.org_id,
        site_id=payload.site_id,
        equipment_tag=payload.equipment_tag,
        equipment_name=payload.equipment_name,
        equipment_type=payload.equipment_type,
        process_unit=payload.process_unit,
        is_safety_critical=payload.is_safety_critical,
        inspection_frequency=payload.inspection_frequency,
        testing_frequency=payload.testing_frequency,
        next_inspection_due=next_inspection,
        owner_id=payload.owner_id,
        equipment_status="in_service",
        created_by=current_user.user_id,
    )
    
    db.add(equipment)
    db.commit()
    db.refresh(equipment)
    
    return {"success": True, "data": {"id": equipment.id}, "message": "Equipment registered"}


# ============================================================================
# Dashboard & Analytics
# ============================================================================

@router.get("/dashboard")
def get_psm_dashboard(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get PSM program dashboard metrics."""
    
    # PSM elements compliance
    total_elements = db.query(func.count(PSMElement.id)).filter(
        PSMElement.organisation_id == current_user.org_id
    ).scalar()
    
    implemented_elements = db.query(func.count(PSMElement.id)).filter(
        and_(
            PSMElement.organisation_id == current_user.org_id,
            PSMElement.status == "implemented"
        )
    ).scalar()
    
    # PHA studies
    total_pha = db.query(func.count(PHAStudy.id)).filter(
        PHAStudy.organisation_id == current_user.org_id
    ).scalar()
    
    overdue_revalidation = db.query(func.count(PHAStudy.id)).filter(
        and_(
            PHAStudy.organisation_id == current_user.org_id,
            PHAStudy.next_revalidation_due < datetime.now().date()
        )
    ).scalar()
    
    open_recommendations = db.query(func.count(PHARecommendation.id)).join(PHAStudy).filter(
        and_(
            PHAStudy.organisation_id == current_user.org_id,
            PHARecommendation.status == "open"
        )
    ).scalar()
    
    # Critical equipment
    total_equipment = db.query(func.count(CriticalEquipment.id)).filter(
        CriticalEquipment.organisation_id == current_user.org_id
    ).scalar()
    
    overdue_inspections = db.query(func.count(CriticalEquipment.id)).filter(
        and_(
            CriticalEquipment.organisation_id == current_user.org_id,
            CriticalEquipment.next_inspection_due < datetime.now().date()
        )
    ).scalar()
    
    # Compliance percentage
    compliance_pct = (implemented_elements / total_elements * 100) if total_elements > 0 else 0
    
    return {
        "success": True,
        "data": {
            "summary": {
                "total_psm_elements": total_elements,
                "implemented_elements": implemented_elements,
                "compliance_percentage": round(compliance_pct, 1),
                "total_pha_studies": total_pha,
                "overdue_revalidation": overdue_revalidation,
                "open_recommendations": open_recommendations,
                "total_critical_equipment": total_equipment,
                "overdue_inspections": overdue_inspections,
            }
        }
    }
