"""AI Orchestrator endpoints.

Source: Enterprise Architecture ISMS v1.0 Section 7.1:
    POST /api/v1/ai/capabilities/{capability_id}/invoke
    GET  /api/v1/ai/capabilities
    GET  /api/v1/governance/audit-log

Every AI capability on the platform is reached through invoke(). Workflow code
names a capability; the Orchestrator picks the engine. Nothing here chooses an
engine, and nothing bypasses the registry.
"""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.models.orchestrator_decision import OrchestratorDecision
from app.services.orchestrator import get_orchestrator
from app.services.orchestrator.core import UnknownCapability

router = APIRouter(prefix="/ai", tags=["AI Orchestrator"])

# Reading the decision log is a governance function, not a worker one.
GOVERNANCE_ROLES = {
    "Manager", "HSE Manager", "Admin", "Superadmin", "Safety Manager",
    "Safety_Manager", "Director", "Auditor",
}


def _require_governance(role: str) -> None:
    if role.strip().lower() not in {r.lower() for r in GOVERNANCE_ROLES}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{role}' may not read the AI decision log",
        )


class InvokeRequest(BaseModel):
    payload: Dict[str, Any] = Field(default_factory=dict)
    correlation_id: Optional[str] = None
    use_cache: bool = True


def _audit_sink(db: Session, current_user: CurrentUser):
    """Persist one decision. Bound per request so it carries the caller."""
    def sink(result) -> None:
        db.add(OrchestratorDecision(
            organisation_id=current_user.org_id,
            user_id=current_user.user_id,
            correlation_id=result.correlation_id,
            capability_id=result.capability_id,
            capability_version=result.capability_version,
            engine_selected=result.engine_selected,
            engines_tried=result.engines_tried,
            engines_skipped=result.engines_skipped,
            confidence=result.confidence,
            threshold_applied=result.threshold,
            pathway=result.pathway,
            requires_hitl=int(result.requires_hitl),
            hitl_reason=(result.hitl_reason or "")[:255] or None,
            hitl_sla_minutes=result.hitl_sla_minutes,
            hitl_due_at=result.hitl_due_at,
            input_hash=result.input_hash,
            explanation=result.explanation,
            latency_ms=result.latency_ms,
            cost=result.cost,
        ))
        db.commit()
    return sink


@router.get("/capabilities")
def list_capabilities(current_user: CurrentUser = Depends(get_current_user)):
    """The Capability Registry, with where each capability currently resolves.

    `resolves_at_tier` is the honest answer to "does this cost tokens" —
    anything below tier 6 runs deterministically. `adapter_available` false
    means the capability is declared but has no implementation at its preferred
    engine, so it degrades down the chain.
    """
    o = get_orchestrator()
    caps = o.describe()
    llm_count = sum(1 for c in caps if c["invokes_llm"])
    return {
        "capabilities": caps,
        "summary": {
            "total": len(caps),
            "resolve_without_llm": len(caps) - llm_count,
            "resolve_via_llm": llm_count,
            "non_llm_share": round(
                (len(caps) - llm_count) / len(caps), 3) if caps else None,
            "target": "> 0.90 of interactions must not invoke an LLM",
        },
    }


@router.get("/engines")
def list_engines(current_user: CurrentUser = Depends(get_current_user)):
    """Engine Registry with live health and circuit-breaker state."""
    return {"engines": get_orchestrator().engine_status()}


@router.post("/capabilities/{capability_id}/invoke")
def invoke_capability(
    capability_id: str,
    request: InvokeRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Invoke a registered capability through the LEAN hierarchy.

    Returns the result plus the full selection trace: which engine served it,
    which were skipped and why, the confidence against the threshold, and the
    resulting pathway. A pathway of HUMAN_REVIEW or ESCALATE means the result
    must not be acted on until a person signs it off.
    """
    o = get_orchestrator()
    try:
        result = o.invoke(
            capability_id,
            request.payload,
            correlation_id=request.correlation_id or str(uuid.uuid4()),
            use_cache=request.use_cache,
            audit_sink=_audit_sink(db, current_user),
        )
    except UnknownCapability:
        raise HTTPException(
            status_code=404,
            detail=f"Capability '{capability_id}' is not in the registry. "
                   f"See GET /ai/capabilities.",
        )

    return {"success": True, "data": result.to_dict()}


@router.get("/decisions")
def decision_log(
    capability_id: Optional[str] = Query(None),
    pathway: Optional[str] = Query(None, description="AUTO_APPROVE | HUMAN_REVIEW | ESCALATE"),
    engine: Optional[str] = Query(None),
    pending_hitl: bool = Query(False, description="Only decisions still awaiting human review"),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """The AI decision audit log (Section 10.3 regulatory access).

    Filterable by capability, pathway, engine and date so a regulator can pull
    every decision of a given kind. Only hashes of inputs are held.
    """
    _require_governance(current_user.role)

    q = db.query(OrchestratorDecision).filter(
        OrchestratorDecision.organisation_id == current_user.org_id)
    if capability_id:
        q = q.filter(OrchestratorDecision.capability_id == capability_id)
    if pathway:
        q = q.filter(OrchestratorDecision.pathway == pathway.upper())
    if engine:
        q = q.filter(OrchestratorDecision.engine_selected == engine)
    if pending_hitl:
        q = q.filter(OrchestratorDecision.requires_hitl == 1)

    rows = q.order_by(OrchestratorDecision.id.desc()).limit(limit).all()
    now = datetime.utcnow()
    return [
        {
            "id": r.id,
            "correlation_id": r.correlation_id,
            "capability_id": r.capability_id,
            "capability_version": r.capability_version,
            "engine_selected": r.engine_selected,
            "engines_tried": r.engines_tried,
            "engines_skipped": r.engines_skipped,
            "confidence": float(r.confidence) if r.confidence is not None else None,
            "threshold": float(r.threshold_applied) if r.threshold_applied is not None else None,
            "pathway": r.pathway,
            "requires_hitl": bool(r.requires_hitl),
            "hitl_reason": r.hitl_reason,
            "hitl_due_at": r.hitl_due_at.isoformat() if r.hitl_due_at else None,
            "hitl_overdue": bool(r.requires_hitl and r.hitl_due_at and r.hitl_due_at < now),
            "input_hash": r.input_hash,
            "explanation": r.explanation,
            "latency_ms": r.latency_ms,
            "cost": float(r.cost or 0),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/decisions/stats")
def decision_stats(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Token-efficiency and pathway distribution — Section 13.2 AI quality metrics."""
    _require_governance(current_user.role)
    from sqlalchemy import func

    rows = (
        db.query(
            OrchestratorDecision.pathway,
            func.count(OrchestratorDecision.id),
            func.sum(OrchestratorDecision.cost),
        )
        .filter(OrchestratorDecision.organisation_id == current_user.org_id)
        .group_by(OrchestratorDecision.pathway)
        .all()
    )
    by_pathway = {p: {"count": c, "cost": float(s or 0)} for p, c, s in rows}
    total = sum(v["count"] for v in by_pathway.values())

    llm_calls = (
        db.query(func.count(OrchestratorDecision.id))
        .filter(OrchestratorDecision.organisation_id == current_user.org_id)
        .filter(OrchestratorDecision.engine_selected.like("LLM-%"))
        .scalar()
    ) or 0

    return {
        "total_decisions": total,
        "by_pathway": by_pathway,
        "llm_invocations": llm_calls,
        "non_llm_share": round((total - llm_calls) / total, 4) if total else None,
        "target_non_llm_share": 0.90,
        "meets_target": ((total - llm_calls) / total >= 0.90) if total else None,
        "total_cost": round(sum(v["cost"] for v in by_pathway.values()), 6),
    }
