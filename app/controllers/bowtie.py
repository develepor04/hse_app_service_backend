"""WF-13: Barrier/Bowtie Analysis API Endpoints

Bowtie methodology endpoints for:
- Bowtie diagram CRUD
- Threat and consequence pathway management
- Barrier effectiveness tracking
- Verification workflows
- Incident linkage
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload

from app.config.database import get_db
from app.core.dependencies import CurrentUser, get_current_user
from app.models.bowtie import (
    BowtieDiagram, BowtieThreat, BowtieConsequence, BowtieBarrier,
    BowtieBarrierVerification, BowtieIncidentLink, BowtieReview,
    BowtieBarrierAlert
)
from app.utils.logger import get_logger

router = APIRouter(prefix="/bowtie", tags=["Barrier/Bowtie Analysis"])
logger = get_logger(__name__)


# ============================================================================
# Pydantic Schemas
# ============================================================================

class ThreatCreate(BaseModel):
    threat_name: str
    threat_desc: Optional[str] = None
    threat_type: Optional[str] = None
    base_likelihood: Optional[int] = Field(None, ge=1, le=5)
    display_order: int = 0


class ConsequenceCreate(BaseModel):
    consequence_name: str
    consequence_desc: Optional[str] = None
    consequence_type: Optional[str] = None
    max_severity: Optional[int] = Field(None, ge=1, le=5)
    max_fatalities: Optional[int] = None
    max_injuries: Optional[int] = None
    financial_impact: Optional[float] = None
    environmental_impact: Optional[str] = None
    reputational_impact: Optional[str] = None
    display_order: int = 0


class BarrierCreate(BaseModel):
    threat_id: Optional[int] = None
    consequence_id: Optional[int] = None
    barrier_side: str = Field(..., pattern="^(preventive|mitigative)$")
    barrier_name: str
    barrier_desc: Optional[str] = None
    barrier_type: Optional[str] = None
    control_type: Optional[str] = None
    independence_level: Optional[int] = Field(None, ge=1, le=3)
    design_effectiveness: Optional[int] = Field(None, ge=1, le=5)
    actual_effectiveness: Optional[int] = Field(None, ge=1, le=5)
    verification_method: Optional[str] = None
    verification_frequency: Optional[int] = None
    performance_standard: Optional[str] = None
    failure_criteria: Optional[str] = None
    owner_id: Optional[int] = None
    display_order: int = 0


class BowtieDiagramCreate(BaseModel):
    top_event_name: str
    top_event_desc: Optional[str] = None
    hazard_category_id: Optional[int] = None
    site_id: Optional[int] = None
    process_unit: Optional[str] = None
    inherent_severity: Optional[int] = Field(None, ge=1, le=5)
    inherent_likelihood: Optional[int] = Field(None, ge=1, le=5)
    owner_id: Optional[int] = None
    review_frequency: int = 12


class BarrierVerificationCreate(BaseModel):
    barrier_id: int
    verification_date: str
    verification_type: str
    verified_by: Optional[int] = None
    result: str = Field(..., pattern="^(pass|fail|degraded|not_tested)$")
    effectiveness_rating: Optional[int] = Field(None, ge=1, le=5)
    findings: Optional[str] = None
    deficiencies_found: Optional[str] = None
    corrective_actions: Optional[str] = None
    action_owner: Optional[int] = None
    action_due_date: Optional[str] = None



# ============================================================================
# Helper Functions
# ============================================================================

def calculate_risk_score(severity: Optional[int], likelihood: Optional[int]) -> Optional[int]:
    """Calculate risk score as L x S."""
    if severity and likelihood:
        return severity * likelihood
    return None


def calculate_residual_risk(bowtie: BowtieDiagram, db: Session) -> tuple:
    """Calculate residual risk after accounting for barrier effectiveness.
    
    Returns: (residual_likelihood, residual_severity, residual_score)
    """
    if not bowtie.inherent_likelihood or not bowtie.inherent_severity:
        return None, None, None
    
    # Get all operational preventive barriers
    preventive_barriers = db.query(BowtieBarrier).filter(
        and_(
            BowtieBarrier.bowtie_id == bowtie.id,
            BowtieBarrier.barrier_side == "preventive",
            BowtieBarrier.status == "operational"
        )
    ).all()
    
    # Calculate combined likelihood reduction
    likelihood_factor = 1.0
    for barrier in preventive_barriers:
        if barrier.risk_reduction_factor:
            likelihood_factor *= float(barrier.risk_reduction_factor)
    
    residual_likelihood = max(1, int(bowtie.inherent_likelihood * likelihood_factor))
    
    # Get all operational mitigative barriers
    mitigative_barriers = db.query(BowtieBarrier).filter(
        and_(
            BowtieBarrier.bowtie_id == bowtie.id,
            BowtieBarrier.barrier_side == "mitigative",
            BowtieBarrier.status == "operational"
        )
    ).all()
    
    # Calculate combined severity reduction
    severity_factor = 1.0
    for barrier in mitigative_barriers:
        if barrier.risk_reduction_factor:
            severity_factor *= float(barrier.risk_reduction_factor)
    
    residual_severity = max(1, int(bowtie.inherent_severity * severity_factor))
    residual_score = residual_likelihood * residual_severity
    
    return residual_likelihood, residual_severity, residual_score



# ============================================================================
# Bowtie Diagram Endpoints
# ============================================================================

@router.get("/diagrams")
def list_bowtie_diagrams(
    site_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    overdue_review: bool = Query(False),
    high_risk_only: bool = Query(False),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List all bowtie diagrams for organization."""
    q = db.query(BowtieDiagram).filter(
        BowtieDiagram.organisation_id == current_user.org_id
    )
    
    if site_id:
        q = q.filter(BowtieDiagram.site_id == site_id)
    
    if status:
        q = q.filter(BowtieDiagram.status == status)
    
    if overdue_review:
        q = q.filter(BowtieDiagram.next_review_due < datetime.now().date())
    
    if high_risk_only:
        q = q.filter(BowtieDiagram.residual_risk_score >= 15)  # Critical/High risk
    
    diagrams = q.order_by(BowtieDiagram.residual_risk_score.desc()).limit(limit).all()
    
    return {
        "success": True,
        "data": [
            {
                "id": d.id,
                "top_event_name": d.top_event_name,
                "top_event_desc": d.top_event_desc,
                "site_id": d.site_id,
                "process_unit": d.process_unit,
                "inherent_risk_score": d.inherent_risk_score,
                "residual_risk_score": d.residual_risk_score,
                "target_risk_score": d.target_risk_score,
                "status": d.status,
                "next_review_due": d.next_review_due.isoformat() if d.next_review_due else None,
                "owner_id": d.owner_id,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in diagrams
        ],
        "total": q.count(),
    }



@router.get("/diagrams/{bowtie_id}")
def get_bowtie_diagram(
    bowtie_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get complete bowtie diagram with all pathways and barriers."""
    bowtie = db.query(BowtieDiagram).filter(
        and_(
            BowtieDiagram.id == bowtie_id,
            BowtieDiagram.organisation_id == current_user.org_id
        )
    ).options(
        joinedload(BowtieDiagram.threats),
        joinedload(BowtieDiagram.consequences),
        joinedload(BowtieDiagram.barriers)
    ).first()
    
    if not bowtie:
        raise HTTPException(status_code=404, detail="Bowtie diagram not found")
    
    # Build complete bowtie structure
    threats = []
    for threat in bowtie.threats:
        preventive_barriers = [
            {
                "id": b.id,
                "barrier_name": b.barrier_name,
                "barrier_type": b.barrier_type,
                "status": b.status,
                "actual_effectiveness": b.actual_effectiveness,
                "next_verification_due": b.next_verification_due.isoformat() if b.next_verification_due else None,
            }
            for b in threat.barriers if b.barrier_side == "preventive"
        ]
        threats.append({
            "id": threat.id,
            "threat_name": threat.threat_name,
            "threat_desc": threat.threat_desc,
            "threat_type": threat.threat_type,
            "base_likelihood": threat.base_likelihood,
            "preventive_barriers": preventive_barriers,
        })
    
    consequences = []
    for cons in bowtie.consequences:
        mitigative_barriers = [
            {
                "id": b.id,
                "barrier_name": b.barrier_name,
                "barrier_type": b.barrier_type,
                "status": b.status,
                "actual_effectiveness": b.actual_effectiveness,
                "next_verification_due": b.next_verification_due.isoformat() if b.next_verification_due else None,
            }
            for b in cons.barriers if b.barrier_side == "mitigative"
        ]
        consequences.append({
            "id": cons.id,
            "consequence_name": cons.consequence_name,
            "consequence_desc": cons.consequence_desc,
            "consequence_type": cons.consequence_type,
            "max_severity": cons.max_severity,
            "max_fatalities": cons.max_fatalities,
            "mitigative_barriers": mitigative_barriers,
        })
    
    return {
        "success": True,
        "data": {
            "id": bowtie.id,
            "top_event_name": bowtie.top_event_name,
            "top_event_desc": bowtie.top_event_desc,
            "site_id": bowtie.site_id,
            "process_unit": bowtie.process_unit,
            "inherent_severity": bowtie.inherent_severity,
            "inherent_likelihood": bowtie.inherent_likelihood,
            "inherent_risk_score": bowtie.inherent_risk_score,
            "residual_severity": bowtie.residual_severity,
            "residual_likelihood": bowtie.residual_likelihood,
            "residual_risk_score": bowtie.residual_risk_score,
            "target_severity": bowtie.target_severity,
            "target_likelihood": bowtie.target_likelihood,
            "target_risk_score": bowtie.target_risk_score,
            "status": bowtie.status,
            "review_frequency": bowtie.review_frequency,
            "last_reviewed_at": bowtie.last_reviewed_at.isoformat() if bowtie.last_reviewed_at else None,
            "next_review_due": bowtie.next_review_due.isoformat() if bowtie.next_review_due else None,
            "owner_id": bowtie.owner_id,
            "threats": threats,
            "consequences": consequences,
        }
    }



@router.post("/diagrams")
def create_bowtie_diagram(
    payload: BowtieDiagramCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Create a new bowtie diagram."""
    # Calculate inherent risk
    inherent_risk_score = calculate_risk_score(
        payload.inherent_severity, payload.inherent_likelihood
    )
    
    # Set next review date
    next_review_due = datetime.now() + timedelta(days=payload.review_frequency * 30)
    
    bowtie = BowtieDiagram(
        organisation_id=current_user.org_id,
        top_event_name=payload.top_event_name,
        top_event_desc=payload.top_event_desc,
        hazard_category_id=payload.hazard_category_id,
        site_id=payload.site_id,
        process_unit=payload.process_unit,
        inherent_severity=payload.inherent_severity,
        inherent_likelihood=payload.inherent_likelihood,
        inherent_risk_score=inherent_risk_score,
        owner_id=payload.owner_id,
        review_frequency=payload.review_frequency,
        next_review_due=next_review_due.date(),
        status="active",
        created_by=current_user.user_id,
    )
    
    db.add(bowtie)
    db.commit()
    db.refresh(bowtie)
    
    logger.info(
        f"Bowtie diagram created: {bowtie.top_event_name} (ID {bowtie.id}) by user {current_user.user_id}"
    )
    
    return {"success": True, "data": {"id": bowtie.id}, "message": "Bowtie diagram created"}



# ============================================================================
# Threat Pathway Endpoints
# ============================================================================

@router.post("/diagrams/{bowtie_id}/threats")
def add_threat(
    bowtie_id: int,
    payload: ThreatCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Add a threat pathway to bowtie diagram."""
    bowtie = db.query(BowtieDiagram).filter(
        and_(
            BowtieDiagram.id == bowtie_id,
            BowtieDiagram.organisation_id == current_user.org_id
        )
    ).first()
    
    if not bowtie:
        raise HTTPException(status_code=404, detail="Bowtie diagram not found")
    
    threat = BowtieThreat(
        bowtie_id=bowtie_id,
        threat_name=payload.threat_name,
        threat_desc=payload.threat_desc,
        threat_type=payload.threat_type,
        base_likelihood=payload.base_likelihood,
        display_order=payload.display_order,
    )
    
    db.add(threat)
    db.commit()
    db.refresh(threat)
    
    return {"success": True, "data": {"id": threat.id}, "message": "Threat added"}


# ============================================================================
# Consequence Pathway Endpoints
# ============================================================================

@router.post("/diagrams/{bowtie_id}/consequences")
def add_consequence(
    bowtie_id: int,
    payload: ConsequenceCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Add a consequence pathway to bowtie diagram."""
    bowtie = db.query(BowtieDiagram).filter(
        and_(
            BowtieDiagram.id == bowtie_id,
            BowtieDiagram.organisation_id == current_user.org_id
        )
    ).first()
    
    if not bowtie:
        raise HTTPException(status_code=404, detail="Bowtie diagram not found")
    
    consequence = BowtieConsequence(
        bowtie_id=bowtie_id,
        consequence_name=payload.consequence_name,
        consequence_desc=payload.consequence_desc,
        consequence_type=payload.consequence_type,
        max_severity=payload.max_severity,
        max_fatalities=payload.max_fatalities,
        max_injuries=payload.max_injuries,
        financial_impact=payload.financial_impact,
        environmental_impact=payload.environmental_impact,
        reputational_impact=payload.reputational_impact,
        display_order=payload.display_order,
    )
    
    db.add(consequence)
    db.commit()
    db.refresh(consequence)
    
    return {"success": True, "data": {"id": consequence.id}, "message": "Consequence added"}



# ============================================================================
# Barrier Endpoints
# ============================================================================

@router.post("/diagrams/{bowtie_id}/barriers")
def add_barrier(
    bowtie_id: int,
    payload: BarrierCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Add a barrier (preventive or mitigative control) to bowtie diagram."""
    bowtie = db.query(BowtieDiagram).filter(
        and_(
            BowtieDiagram.id == bowtie_id,
            BowtieDiagram.organisation_id == current_user.org_id
        )
    ).first()
    
    if not bowtie:
        raise HTTPException(status_code=404, detail="Bowtie diagram not found")
    
    # Validate linkage
    if payload.barrier_side == "preventive" and not payload.threat_id:
        raise HTTPException(status_code=400, detail="Preventive barriers must link to a threat")
    if payload.barrier_side == "mitigative" and not payload.consequence_id:
        raise HTTPException(status_code=400, detail="Mitigative barriers must link to a consequence")
    
    # Calculate risk reduction factor from effectiveness
    risk_reduction_factor = None
    if payload.design_effectiveness:
        # Convert effectiveness (1-5) to reduction factor
        # 5 = 95% effective (0.05 factor), 4 = 80% (0.20), 3 = 50% (0.50), etc.
        effectiveness_map = {5: 0.05, 4: 0.20, 3: 0.50, 2: 0.70, 1: 0.90}
        risk_reduction_factor = effectiveness_map.get(payload.design_effectiveness, 0.50)
    
    # Set next verification date
    next_verification_due = None
    if payload.verification_frequency:
        next_verification_due = (datetime.now() + timedelta(days=payload.verification_frequency)).date()
    
    barrier = BowtieBarrier(
        bowtie_id=bowtie_id,
        threat_id=payload.threat_id,
        consequence_id=payload.consequence_id,
        barrier_side=payload.barrier_side,
        barrier_name=payload.barrier_name,
        barrier_desc=payload.barrier_desc,
        barrier_type=payload.barrier_type,
        control_type=payload.control_type,
        independence_level=payload.independence_level,
        design_effectiveness=payload.design_effectiveness,
        actual_effectiveness=payload.actual_effectiveness or payload.design_effectiveness,
        risk_reduction_factor=risk_reduction_factor,
        verification_method=payload.verification_method,
        verification_frequency=payload.verification_frequency,
        next_verification_due=next_verification_due,
        performance_standard=payload.performance_standard,
        failure_criteria=payload.failure_criteria,
        owner_id=payload.owner_id,
        status="operational",
        display_order=payload.display_order,
    )
    
    db.add(barrier)
    db.commit()
    db.refresh(barrier)
    
    # Recalculate residual risk
    res_l, res_s, res_score = calculate_residual_risk(bowtie, db)
    bowtie.residual_likelihood = res_l
    bowtie.residual_severity = res_s
    bowtie.residual_risk_score = res_score
    db.commit()
    
    logger.info(
        f"Barrier added to bowtie {bowtie_id}: {barrier.barrier_name} ({payload.barrier_side})"
    )
    
    return {"success": True, "data": {"id": barrier.id}, "message": "Barrier added"}



@router.get("/barriers/due-verification")
def get_overdue_barriers(
    days_ahead: int = Query(30),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get barriers with overdue or upcoming verification."""
    cutoff_date = (datetime.now() + timedelta(days=days_ahead)).date()
    
    barriers = db.query(BowtieBarrier).join(BowtieDiagram).filter(
        and_(
            BowtieDiagram.organisation_id == current_user.org_id,
            BowtieBarrier.next_verification_due <= cutoff_date,
            BowtieBarrier.status.in_(["operational", "degraded"])
        )
    ).order_by(BowtieBarrier.next_verification_due).all()
    
    return {
        "success": True,
        "data": [
            {
                "id": b.id,
                "barrier_name": b.barrier_name,
                "bowtie_id": b.bowtie_id,
                "barrier_side": b.barrier_side,
                "status": b.status,
                "next_verification_due": b.next_verification_due.isoformat() if b.next_verification_due else None,
                "days_overdue": (datetime.now().date() - b.next_verification_due).days if b.next_verification_due < datetime.now().date() else 0,
                "owner_id": b.owner_id,
            }
            for b in barriers
        ],
        "total": len(barriers),
    }


# ============================================================================
# Barrier Verification Endpoints
# ============================================================================

@router.post("/barriers/verify")
def verify_barrier(
    payload: BarrierVerificationCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Record a barrier verification/inspection."""
    barrier = db.query(BowtieBarrier).join(BowtieDiagram).filter(
        and_(
            BowtieBarrier.id == payload.barrier_id,
            BowtieDiagram.organisation_id == current_user.org_id
        )
    ).first()
    
    if not barrier:
        raise HTTPException(status_code=404, detail="Barrier not found")
    
    verification_date = datetime.strptime(payload.verification_date, "%Y-%m-%d").date()
    
    # Calculate next verification date
    next_verification_due = None
    if barrier.verification_frequency:
        next_verification_due = (verification_date + timedelta(days=barrier.verification_frequency))
    
    verification = BowtieBarrierVerification(
        barrier_id=payload.barrier_id,
        organisation_id=current_user.org_id,
        verification_date=verification_date,
        verification_type=payload.verification_type,
        verified_by=payload.verified_by,
        result=payload.result,
        effectiveness_rating=payload.effectiveness_rating,
        findings=payload.findings,
        deficiencies_found=payload.deficiencies_found,
        corrective_actions=payload.corrective_actions,
        action_owner=payload.action_owner,
        action_due_date=datetime.strptime(payload.action_due_date, "%Y-%m-%d").date() if payload.action_due_date else None,
        next_verification_due=next_verification_due,
    )
    
    db.add(verification)
    
    # Update barrier status and effectiveness
    barrier.last_verified_at = datetime.now()
    barrier.next_verification_due = next_verification_due
    
    if payload.result == "pass":
        barrier.status = "operational"
        if payload.effectiveness_rating:
            barrier.actual_effectiveness = payload.effectiveness_rating
    elif payload.result in ["fail", "degraded"]:
        barrier.status = "degraded"
        barrier.degraded_since = datetime.now()
        barrier.degradation_reason = payload.deficiencies_found
        if payload.effectiveness_rating:
            barrier.actual_effectiveness = payload.effectiveness_rating
        
        # Create alert
        alert = BowtieBarrierAlert(
            barrier_id=barrier.id,
            bowtie_id=barrier.bowtie_id,
            organisation_id=current_user.org_id,
            alert_type="failed_test" if payload.result == "fail" else "degraded",
            severity="critical" if payload.result == "fail" else "high",
            alert_message=f"Barrier '{barrier.barrier_name}' {payload.result} verification: {payload.deficiencies_found}",
            assigned_to=barrier.owner_id or payload.action_owner,
        )
        db.add(alert)
    
    db.commit()
    
    # Recalculate residual risk after verification
    bowtie = db.query(BowtieDiagram).filter(BowtieDiagram.id == barrier.bowtie_id).first()
    if bowtie:
        res_l, res_s, res_score = calculate_residual_risk(bowtie, db)
        bowtie.residual_likelihood = res_l
        bowtie.residual_severity = res_s
        bowtie.residual_risk_score = res_score
        db.commit()
    
    logger.info(
        f"Barrier verification recorded: {barrier.barrier_name} - {payload.result}"
    )
    
    return {"success": True, "message": "Barrier verification recorded"}



# ============================================================================
# Dashboard & Analytics
# ============================================================================

@router.get("/dashboard")
def get_bowtie_dashboard(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get bowtie analysis dashboard metrics."""
    
    # Total bowties
    total_bowties = db.query(func.count(BowtieDiagram.id)).filter(
        BowtieDiagram.organisation_id == current_user.org_id
    ).scalar()
    
    # High-risk bowties (residual score >= 15)
    high_risk_bowties = db.query(func.count(BowtieDiagram.id)).filter(
        and_(
            BowtieDiagram.organisation_id == current_user.org_id,
            BowtieDiagram.residual_risk_score >= 15
        )
    ).scalar()
    
    # Overdue reviews
    overdue_reviews = db.query(func.count(BowtieDiagram.id)).filter(
        and_(
            BowtieDiagram.organisation_id == current_user.org_id,
            BowtieDiagram.next_review_due < datetime.now().date()
        )
    ).scalar()
    
    # Total barriers
    total_barriers = db.query(func.count(BowtieBarrier.id)).join(BowtieDiagram).filter(
        BowtieDiagram.organisation_id == current_user.org_id
    ).scalar()
    
    # Degraded barriers
    degraded_barriers = db.query(func.count(BowtieBarrier.id)).join(BowtieDiagram).filter(
        and_(
            BowtieDiagram.organisation_id == current_user.org_id,
            BowtieBarrier.status == "degraded"
        )
    ).scalar()
    
    # Overdue verifications
    overdue_verifications = db.query(func.count(BowtieBarrier.id)).join(BowtieDiagram).filter(
        and_(
            BowtieDiagram.organisation_id == current_user.org_id,
            BowtieBarrier.next_verification_due < datetime.now().date()
        )
    ).scalar()
    
    # Open alerts
    open_alerts = db.query(func.count(BowtieBarrierAlert.id)).filter(
        and_(
            BowtieBarrierAlert.organisation_id == current_user.org_id,
            BowtieBarrierAlert.resolved == False
        )
    ).scalar()
    
    # Barrier effectiveness distribution
    effectiveness_dist = db.query(
        BowtieBarrier.actual_effectiveness,
        func.count(BowtieBarrier.id)
    ).join(BowtieDiagram).filter(
        BowtieDiagram.organisation_id == current_user.org_id
    ).group_by(BowtieBarrier.actual_effectiveness).all()
    
    effectiveness_chart = [
        {"effectiveness": eff or 0, "count": count}
        for eff, count in effectiveness_dist
    ]
    
    # Risk trend (top 10 high-risk bowties)
    high_risk_list = db.query(BowtieDiagram).filter(
        BowtieDiagram.organisation_id == current_user.org_id
    ).order_by(BowtieDiagram.residual_risk_score.desc()).limit(10).all()
    
    risk_trend = [
        {
            "top_event_name": b.top_event_name,
            "inherent_risk": b.inherent_risk_score,
            "residual_risk": b.residual_risk_score,
            "risk_reduction": b.inherent_risk_score - b.residual_risk_score if b.inherent_risk_score and b.residual_risk_score else 0,
        }
        for b in high_risk_list
    ]
    
    return {
        "success": True,
        "data": {
            "summary": {
                "total_bowties": total_bowties,
                "high_risk_bowties": high_risk_bowties,
                "overdue_reviews": overdue_reviews,
                "total_barriers": total_barriers,
                "degraded_barriers": degraded_barriers,
                "overdue_verifications": overdue_verifications,
                "open_alerts": open_alerts,
            },
            "effectiveness_distribution": effectiveness_chart,
            "high_risk_bowties": risk_trend,
        }
    }
