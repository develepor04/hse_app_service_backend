"""THE INTEGRATION SPINE · deterministic gate engine endpoints.

    any         POST /gates/permit-check     run all six gates for a permit
    any         POST /gates/journey-check    gates that apply at departure
    supervisor  POST /gates/override         D4 core feature — reason, context, outcome
    any         GET  /gates/log              the gate decision log
    auditor     GET  /gates/overrides        the regulatory defensibility record

Rule-based and auditable. The AI layer may add context but never changes a
verdict, and two verdicts can never be overridden at all: an expired
safety-critical certificate, and a fatigue index of 20 or more.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
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
from app.models.gates import GateDecisionLog, OverrideLog
from app.models.permit_to_work import PermitToWork
from app.models.transport import JourneyPlan
from app.schemas.gates import (
    GateDecisionOut,
    GateEvaluationOut,
    JourneyGateCheck,
    OverrideCreate,
    OverrideOut,
    PermitGateCheck,
)
from app.services.gate_engine import evaluate_journey_gates, evaluate_permit_gates

router = APIRouter(prefix="/gates", tags=["Gate Engine"])

# Roles entitled to override a gate at all. A worker never can.
OVERRIDE_ROLES = SUPERVISOR_ROLES | MANAGER_ROLES


@router.post("/permit-check", response_model=GateEvaluationOut)
def permit_check(
    payload: PermitGateCheck,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    permit = (
        db.query(PermitToWork)
        .filter(PermitToWork.id == payload.permit_id)
        .filter(PermitToWork.organisation_id == current_user.org_id)
        .first()
    )
    if not permit:
        raise HTTPException(status_code=404, detail="Permit not found")

    evaluation = evaluate_permit_gates(
        db,
        current_user.org_id,
        permit,
        employee_ids=payload.employee_ids,
        evaluated_by=employee_id_for(db, current_user.user_id),
        persist=payload.persist,
    )

    # The verdict rides on the permit so the web console and every mobile role
    # read the same gate status without recomputing it.
    permit.gate_status = evaluation.overall
    permit.gate_checked_at = datetime.now()
    permit.gate_blocked_reason = "; ".join(evaluation.blocked_reasons) or None
    db.commit()

    return GateEvaluationOut(**evaluation.to_dict())


@router.post("/journey-check", response_model=GateEvaluationOut)
def journey_check(
    payload: JourneyGateCheck,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    journey = (
        db.query(JourneyPlan)
        .filter(JourneyPlan.id == payload.journey_plan_id)
        .filter(JourneyPlan.organisation_id == current_user.org_id)
        .first()
    )
    if not journey:
        raise HTTPException(status_code=404, detail="Journey plan not found")

    evaluation = evaluate_journey_gates(
        db,
        current_user.org_id,
        journey,
        employee_ids=payload.employee_ids,
        weather=payload.weather,
        evaluated_by=employee_id_for(db, current_user.user_id),
        persist=payload.persist,
    )
    return GateEvaluationOut(**evaluation.to_dict())


@router.post("/override", response_model=OverrideOut, status_code=201)
def override_gate(
    payload: OverrideCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Record an override of a gate verdict.

    Refuses outright on a hard block. The spec puts this in writing — "Never
    overrides a safety gate. Where the system hard-blocks work, an expired
    safety-critical certificate, or a driver over the fatigue limit, the AI may
    advise, but it cannot lift that block" — and the same limit binds people
    below Safety Manager.
    """
    require_role(current_user.role, OVERRIDE_ROLES, "override a gate decision")

    decision: Optional[GateDecisionLog] = None
    if payload.gate_decision_id:
        decision = (
            db.query(GateDecisionLog)
            .filter(GateDecisionLog.id == payload.gate_decision_id)
            .filter(GateDecisionLog.organisation_id == current_user.org_id)
            .first()
        )
        if not decision:
            raise HTTPException(status_code=404, detail="Gate decision not found")

        if (decision.details or {}).get("hard"):
            raise HTTPException(
                status_code=403,
                detail=(
                    "This is a hard block and cannot be overridden. An expired "
                    "safety-critical certificate must be renewed, and a fatigue index "
                    "of 20 or more requires 8 h rest with a Safety Manager exception "
                    "recorded against the declaration."
                ),
            )

    now = datetime.now()
    row = OverrideLog(
        organisation_id=current_user.org_id,
        gate_decision_id=payload.gate_decision_id,
        subject_type=payload.subject_type or (decision.subject_type if decision else None),
        subject_id=payload.subject_id or (decision.subject_id if decision else None),
        gate_key=payload.gate_key or (decision.gate_key if decision else None),
        decision=payload.decision,
        reason=payload.reason,
        context=payload.context,
        outcome=payload.outcome,
        original_verdict=decision.verdict if decision else None,
        resulting_verdict=payload.resulting_verdict,
        overridden_by=employee_id_for(db, current_user.user_id),
        overridden_by_role=current_user.role,
        overridden_at=now,
        source_system="mobile",
        last_verified_at=now,
    )
    db.add(row)

    if decision is not None:
        decision.override_history = (decision.override_history or []) + [
            {
                "at": now.isoformat(),
                "by_user_id": current_user.user_id,
                "role": current_user.role,
                "decision": payload.decision,
                "reason": payload.reason,
            }
        ]

    db.commit()
    db.refresh(row)
    return OverrideOut.model_validate(row)


@router.get("/log", response_model=List[GateDecisionOut])
def gate_log(
    subject_type: Optional[str] = None,
    subject_id: Optional[int] = None,
    verdict: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    q = db.query(GateDecisionLog).filter(GateDecisionLog.organisation_id == current_user.org_id)
    if subject_type:
        q = q.filter(GateDecisionLog.subject_type == subject_type)
    if subject_id:
        q = q.filter(GateDecisionLog.subject_id == subject_id)
    if verdict:
        q = q.filter(GateDecisionLog.verdict == verdict)
    rows = q.order_by(GateDecisionLog.id.desc()).limit(limit).all()
    return [GateDecisionOut.model_validate(r) for r in rows]


@router.get("/overrides", response_model=List[OverrideOut])
def override_log(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """The regulatory defensibility record — who overrode what, when and why."""
    require_role(
        current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES | AUDITOR_ROLES,
        "read the override log",
    )
    rows = (
        db.query(OverrideLog)
        .filter(OverrideLog.organisation_id == current_user.org_id)
        .order_by(OverrideLog.id.desc())
        .limit(limit)
        .all()
    )
    return [OverrideOut.model_validate(r) for r in rows]
