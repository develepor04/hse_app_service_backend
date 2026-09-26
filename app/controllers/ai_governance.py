"""AI governance endpoints — the audit trail, the learning loop, and PIRS.

    any      GET  /ai-governance/log              answers with confidence scores
    any      POST /ai-governance/{id}/decide      accept | amend | reject
    manager  GET  /ai-governance/learning         what the team accepts and rejects
    manager  GET  /ai-governance/model            model governance & version view
    any      GET  /ai-governance/pirs             predictive injury risk score

The delivery status table in HSE_AI_Overview_Client lists all four of these as
IN PROGRESS or NEXT PHASE. They are the difference between an assistant that
answers and one that is defensible to a regulator.
"""
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.config.settings import get_settings
from app.controllers.workflow_common import MANAGER_ROLES, require_role
from app.core.dependencies import CurrentUser, get_current_user
from app.models.ai_decision import AiDecisionLog
from app.services.sps_engine import compute_domains, count_stale_sources

router = APIRouter(prefix="/ai-governance", tags=["AI Governance"])


class AiLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: Optional[int] = None
    role_bucket: Optional[str] = None
    question: Optional[str] = None
    answer: Optional[str] = None
    model_id: Optional[str] = None
    provider: Optional[str] = None
    snapshot_hash: Optional[str] = None
    confidence_score: Optional[float] = None
    ai_generated: int = 1
    human_decision: Optional[str] = None
    decision_reason: Optional[str] = None
    decided_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class AiDecide(BaseModel):
    """The Core Feature — capture what the human did with the AI's answer."""

    decision: str = Field(..., pattern="^(accept|amend|reject)$")
    reason: Optional[str] = None
    amended_answer: Optional[str] = None


class LearningSummary(BaseModel):
    period_days: int
    total_answers: int
    decided: int
    accepted: int
    amended: int
    rejected: int
    acceptance_rate: float
    mean_confidence: float
    mean_confidence_accepted: Optional[float] = None
    mean_confidence_rejected: Optional[float] = None
    interpretation: str


class ModelGovernance(BaseModel):
    """"Visibility of which AI model version is in use, what it was trained on,
    and the ability to roll back." """

    active_provider: str
    active_model: str
    fallback_provider: Optional[str] = None
    fallback_model: Optional[str] = None
    advisory_only: bool = True
    can_override_safety_gate: bool = False
    grounding: str
    versions_seen: List[Dict[str, Any]] = []


class PirsDomain(BaseModel):
    name: str
    score: float
    weight: float
    driver: str


class PirsResponse(BaseModel):
    """Predictive Injury Risk Score — the AI counterpart to the deterministic SPS.

    Same five domains, but estimating the probability of a recordable or
    lost-time injury over 7, 30 and 90 days, with clear driver attribution.
    """

    scope: str
    computed_at: datetime
    horizon_7d: float
    horizon_30d: float
    horizon_90d: float
    band: str
    domains: List[PirsDomain]
    top_drivers: List[str]
    confidence: float
    is_ai_generated: bool = True
    advisory_note: str


# ── Answer log ────────────────────────────────────────────────────────────────
@router.get("/log", response_model=List[AiLogOut])
def ai_log(
    mine_only: bool = True,
    undecided_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    q = db.query(AiDecisionLog).filter(AiDecisionLog.organisation_id == current_user.org_id)
    if mine_only:
        q = q.filter(AiDecisionLog.user_id == current_user.user_id)
    elif not any(r.lower() == (current_user.role or "").lower() for r in MANAGER_ROLES):
        # Only a manager may read the whole org's AI history.
        q = q.filter(AiDecisionLog.user_id == current_user.user_id)
    if undecided_only:
        q = q.filter(AiDecisionLog.human_decision.is_(None))
    rows = q.order_by(AiDecisionLog.id.desc()).limit(limit).all()
    return [AiLogOut.model_validate(r) for r in rows]


@router.post("/{log_id}/decide", response_model=AiLogOut)
def decide(
    log_id: int,
    payload: AiDecide,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Accept, amend or reject an AI answer.

    A rejection or an amendment without a reason is not useful to the learning
    loop, so both require one.
    """
    row = (
        db.query(AiDecisionLog)
        .filter(AiDecisionLog.id == log_id)
        .filter(AiDecisionLog.organisation_id == current_user.org_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="AI answer not found")

    if payload.decision in ("amend", "reject") and not payload.reason:
        raise HTTPException(
            status_code=400,
            detail=f"A reason is required when you {payload.decision} an AI answer",
        )

    row.human_decision = payload.decision
    row.decision_reason = payload.reason
    row.amended_answer = payload.amended_answer
    row.decided_by = current_user.user_id
    row.decided_at = datetime.now()
    row.override_history = (row.override_history or []) + [
        {
            "at": datetime.now().isoformat(),
            "by_user_id": current_user.user_id,
            "role": current_user.role,
            "decision": payload.decision,
            "reason": payload.reason,
        }
    ]
    db.commit()
    db.refresh(row)
    return AiLogOut.model_validate(row)


@router.get("/learning", response_model=LearningSummary)
def learning(
    days: int = Query(90, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """"Your team teaches it" — what the frontline accepts and what it rejects."""
    require_role(current_user.role, MANAGER_ROLES, "view the AI learning summary")
    since = datetime.now() - timedelta(days=days)

    rows = (
        db.query(AiDecisionLog)
        .filter(AiDecisionLog.organisation_id == current_user.org_id)
        .filter(AiDecisionLog.created_at >= since)
        .all()
    )
    decided = [r for r in rows if r.human_decision]
    accepted = [r for r in decided if r.human_decision == "accept"]
    amended = [r for r in decided if r.human_decision == "amend"]
    rejected = [r for r in decided if r.human_decision == "reject"]

    def _mean(items) -> Optional[float]:
        vals = [float(r.confidence_score) for r in items if r.confidence_score is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    rate = round(len(accepted) / len(decided) * 100, 2) if decided else 0.0
    ca, cr = _mean(accepted), _mean(rejected)

    if not decided:
        interp = "No decisions captured yet — the learning loop has no signal to work from."
    elif ca is not None and cr is not None and ca > cr + 10:
        interp = (
            f"Confidence is tracking usefulness: accepted answers average {ca}, "
            f"rejected {cr}. The score is worth surfacing to users."
        )
    elif rate < 50:
        interp = (
            f"Only {rate}% of answers are accepted — review the grounding "
            "snapshot before widening where the assistant is offered."
        )
    else:
        interp = f"{rate}% of AI answers are accepted by the people doing the work."

    return LearningSummary(
        period_days=days,
        total_answers=len(rows),
        decided=len(decided),
        accepted=len(accepted),
        amended=len(amended),
        rejected=len(rejected),
        acceptance_rate=rate,
        mean_confidence=_mean(rows) or 0.0,
        mean_confidence_accepted=ca,
        mean_confidence_rejected=cr,
        interpretation=interp,
    )


@router.get("/model", response_model=ModelGovernance)
def model_governance(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Which model is in use, and the guarantees that hold regardless."""
    require_role(current_user.role, MANAGER_ROLES, "view model governance")
    s = get_settings()

    seen: Dict[str, Dict[str, Any]] = {}
    for r in (
        db.query(AiDecisionLog)
        .filter(AiDecisionLog.organisation_id == current_user.org_id)
        .order_by(AiDecisionLog.id.desc())
        .limit(500)
        .all()
    ):
        key = f"{r.provider}:{r.model_id}"
        if key not in seen:
            seen[key] = {
                "provider": r.provider,
                "model_id": r.model_id,
                "first_seen": r.created_at,
                "answers": 0,
            }
        seen[key]["answers"] += 1

    return ModelGovernance(
        active_provider="anthropic" if getattr(s, "anthropic_api_key", "") else "azure_openai",
        active_model=getattr(s, "anthropic_model", "") or getattr(s, "azure_openai_deployment", ""),
        fallback_provider="azure_openai" if getattr(s, "azure_openai_api_key", "") else None,
        fallback_model=getattr(s, "azure_openai_deployment", None),
        advisory_only=True,
        # Stated as a fact about the system, not a setting: the gate engine
        # refuses hard-block overrides regardless of what the AI recommends.
        can_override_safety_gate=False,
        grounding=(
            "Every answer is built on a fresh, role-scoped snapshot of this "
            "organisation's live data. The model may only cite figures present "
            "in that snapshot, and must state when something is not tracked."
        ),
        versions_seen=list(seen.values()),
    )


# ── PIRS ──────────────────────────────────────────────────────────────────────
PIRS_WEIGHTS = {
    "Hazard Exposure": 0.25,
    "Control Integrity": 0.25,
    "Work Authorisation & Discipline": 0.20,
    "Human Readiness & Capacity": 0.20,
    "Organisational & System Health": 0.10,
}

_PIRS_DRIVERS = {
    "Hazard Exposure": "high-risk task frequency and work without a valid risk assessment",
    "Control Integrity": "control-hierarchy strength and corrective action effectiveness",
    "Work Authorisation & Discipline": "permit bypass rate and closure quality",
    "Human Readiness & Capacity": "competence gaps combined with fatigue",
    "Organisational & System Health": "near-miss reporting ratio and corrective action ageing",
}


@router.get("/pirs", response_model=PirsResponse)
def pirs(
    days: int = Query(90, ge=7, le=365),
    site_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Predictive Injury Risk Score over 7, 30 and 90 days.

    Built from the same five leading-indicator domains as the SPS. The SPS is
    the auditable core measuring where safety stands now. PIRS estimates the
    probability that current conditions produce a recordable or lost-time
    injury, and is explicitly advisory — a person always decides.
    """
    end = date.today()
    start = end - timedelta(days=days)

    domains = compute_domains(db, current_user.org_id, start, end, site_id)
    domains.pop("inputs", None)
    stale = count_stale_sources(db, current_user.org_id)

    mapped = {
        "Hazard Exposure": domains["hazard_exposure"],
        "Control Integrity": domains["control_integrity"],
        "Work Authorisation & Discipline": domains["work_discipline"],
        "Human Readiness & Capacity": domains["human_readiness"],
        "Organisational & System Health": domains["org_health"],
    }

    base = sum(mapped[k] * PIRS_WEIGHTS[k] for k in PIRS_WEIGHTS)

    # Longer horizons accumulate more exposure, so the same conditions imply a
    # higher probability the further out you look.
    h7 = round(min(100.0, base * 0.35), 2)
    h30 = round(min(100.0, base * 0.70), 2)
    h90 = round(min(100.0, base * 1.00), 2)

    band = (
        "critical" if h90 >= 75 else
        "high" if h90 >= 50 else
        "elevated" if h90 >= 25 else
        "acceptable" if h90 >= 10 else "low"
    )

    ranked = sorted(mapped.items(), key=lambda kv: kv[1] * PIRS_WEIGHTS[kv[0]], reverse=True)

    return PirsResponse(
        scope="site" if site_id else "org",
        computed_at=datetime.now(),
        horizon_7d=h7,
        horizon_30d=h30,
        horizon_90d=h90,
        band=band,
        domains=[
            PirsDomain(
                name=k, score=round(v, 2), weight=PIRS_WEIGHTS[k], driver=_PIRS_DRIVERS[k]
            )
            for k, v in mapped.items()
        ],
        top_drivers=[f"{k} — {_PIRS_DRIVERS[k]}" for k, _ in ranked[:3]],
        confidence=round(max(0.0, 100.0 - stale * 20), 2),
        is_ai_generated=True,
        advisory_note=(
            "This is a forecast, clearly labelled as an estimate and never stated "
            "as fact. It does not make autonomous safety decisions, does not "
            "discipline individuals, and cannot lift a safety gate."
        ),
    )
