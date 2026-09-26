"""WF-08 · Contractor & High-Risk Work.

    any         GET  /contractors                      the registry
    manager     POST /contractors                      add a company
    manager     POST /contractors/{id}/prequalify      LTIFR vs IOGP benchmark
    manager     POST /contractors/{id}/suspend
    supervisor  GET  /contractors/{id}/workers         site-access roll-call
    supervisor  POST /contractors/workers/{id}/access  induction + site access
    supervisor  POST /rams-scores                      score a method statement
    auditor     POST /rams-scores/{id}/rescore         independent re-score
    manager     GET  /contractors/scorecards           quarterly scorecard

The registry is web-held master data. Mobile scores against it — the supervisor
scores RAMS on site, the auditor independently re-scores the same rubric.
"""
from datetime import date, datetime
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
from app.models.contractor import (
    ContractorCompany,
    ContractorHours,
    ContractorScorecard,
    ContractorWorker,
    IogpBenchmark,
    RamsScore,
)
from app.schemas.contractor import (
    ContractorCompanyCreate,
    ContractorCompanyResponse,
    ContractorHoursCreate,
    ContractorHoursResponse,
    ContractorWorkerCreate,
    ContractorWorkerResponse,
    IogpBenchmarkCreate,
    PrequalifyRequest,
    PrequalifyResponse,
    RamsRescore,
    RamsScoreCreate,
    RamsScoreResponse,
    ScorecardResponse,
    SiteAccessUpdate,
    SuspendRequest,
)
from app.services.hse_formulae import (
    RAMS_CRITERIA,
    contractor_scorecard_verdict,
    ltifr_vs_benchmark,
    rams_score,
)

router = APIRouter(prefix="/contractors", tags=["Contractor & High-Risk Work"])
rams_router = APIRouter(prefix="/rams-scores", tags=["Contractor & High-Risk Work"])

READ_ROLES = SUPERVISOR_ROLES | MANAGER_ROLES | AUDITOR_ROLES


def _get_company(db: Session, company_id: int, org_id: Optional[int]) -> ContractorCompany:
    row = (
        db.query(ContractorCompany)
        .filter(ContractorCompany.id == company_id)
        .filter(ContractorCompany.organisation_id == org_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Contractor company not found")
    return row


# ══════════════════════════════════════════════════════════════════════════════
# Registry
# ══════════════════════════════════════════════════════════════════════════════
@router.get("", response_model=List[ContractorCompanyResponse])
@router.get("/", response_model=List[ContractorCompanyResponse])
def list_contractors(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    q = db.query(ContractorCompany).filter(
        ContractorCompany.organisation_id == current_user.org_id
    )
    if status:
        q = q.filter(ContractorCompany.prequalification_status == status)
    return [
        ContractorCompanyResponse.model_validate(r)
        for r in q.order_by(ContractorCompany.company_name).all()
    ]


@router.post("", response_model=ContractorCompanyResponse, status_code=201)
@router.post("/", response_model=ContractorCompanyResponse, status_code=201)
def create_contractor(
    payload: ContractorCompanyCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, MANAGER_ROLES, "add a contractor company")
    row = ContractorCompany(
        organisation_id=current_user.org_id,
        source_system="mobile",
        last_reviewed_at=datetime.now(),
        # exclude_none so an omitted field falls back to the column's own
        # default (e.g. prequalification_status, suspended are NOT NULL)
        # instead of an explicit None blowing up the insert.
        **payload.model_dump(exclude_none=True),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ContractorCompanyResponse.model_validate(row)


@router.get("/{company_id}", response_model=ContractorCompanyResponse)
def get_contractor(
    company_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    return ContractorCompanyResponse.model_validate(
        _get_company(db, company_id, current_user.org_id)
    )


@router.post("/{company_id}/prequalify", response_model=PrequalifyResponse)
def prequalify(
    company_id: int,
    payload: PrequalifyRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Insurance, SSIP/CHAS, 3-yr LTIFR/TRIFR.

    The LTIFR verdict is deterministic: >2x the IOGP benchmark is a rejection,
    1.5-2x is conditional with enhanced monitoring. An explicit `status` in the
    payload lets a Safety Manager record a decision that differs from the
    computed one — but the computed verdict is still returned and stored in the
    notes, so the divergence is visible rather than silent.
    """
    require_role(current_user.role, MANAGER_ROLES, "pre-qualify a contractor")
    co = _get_company(db, company_id, current_user.org_id)

    benchmark = (
        db.query(IogpBenchmark)
        .filter(IogpBenchmark.organisation_id == current_user.org_id)
        .filter(
            IogpBenchmark.benchmark_year == payload.benchmark_year
            if payload.benchmark_year
            else IogpBenchmark.id.isnot(None)
        )
        .order_by(IogpBenchmark.benchmark_year.desc())
        .first()
    )

    verdict = ltifr_vs_benchmark(
        float(co.ltifr_3yr) if co.ltifr_3yr is not None else None,
        float(benchmark.ltifr_benchmark) if benchmark else None,
    )

    computed_status = {
        "reject": "barred",
        "conditional": "conditional",
        "approve": "approved",
        "unknown": "pending",
    }[verdict.verdict]

    co.prequalification_status = payload.status or computed_status
    co.prequalified_by = employee_id_for(db, current_user.user_id)
    co.prequalified_at = datetime.now()
    co.last_verified_at = datetime.now()
    if payload.approved_site_ids is not None:
        co.approved_site_ids = payload.approved_site_ids

    note = f"[{datetime.now():%Y-%m-%d}] {verdict.explanation}"
    if payload.status and payload.status != computed_status:
        note += (
            f" Recorded as '{payload.status}' by {current_user.username}, "
            f"differing from the computed '{computed_status}'."
        )
    if payload.notes:
        note += f" Note: {payload.notes}"
    co.prequalification_notes = ((co.prequalification_notes or "") + "\n" + note).strip()

    db.commit()
    db.refresh(co)

    return PrequalifyResponse(
        contractor_company_id=co.id,
        company_name=co.company_name,
        status=co.prequalification_status,
        ltifr_ratio=verdict.ratio,
        ltifr_verdict=verdict.verdict,
        benchmark_ltifr=float(benchmark.ltifr_benchmark) if benchmark else None,
        explanation=verdict.explanation,
    )


@router.post("/{company_id}/suspend", response_model=ContractorCompanyResponse)
def suspend(
    company_id: int,
    payload: SuspendRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, MANAGER_ROLES, "suspend a contractor")
    co = _get_company(db, company_id, current_user.org_id)
    co.suspended = 1 if payload.suspended else 0
    co.suspended_reason = payload.reason
    db.commit()
    db.refresh(co)
    return ContractorCompanyResponse.model_validate(co)


# ══════════════════════════════════════════════════════════════════════════════
# Site control — induction, certs, site access, toolbox roll-call
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/{company_id}/workers", response_model=List[ContractorWorkerResponse])
def list_workers(
    company_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, READ_ROLES, "view contractor workers")
    rows = (
        db.query(ContractorWorker)
        .filter(ContractorWorker.contractor_company_id == company_id)
        .filter(ContractorWorker.organisation_id == current_user.org_id)
        .all()
    )
    return [ContractorWorkerResponse.model_validate(r) for r in rows]


@router.post("/workers", response_model=ContractorWorkerResponse, status_code=201)
def create_worker(
    payload: ContractorWorkerCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES, "register a contractor worker")
    row = ContractorWorker(
        organisation_id=current_user.org_id,
        source_system="mobile",
        **payload.model_dump(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ContractorWorkerResponse.model_validate(row)


@router.post("/hours", response_model=ContractorHoursResponse, status_code=201)
def create_contractor_hours(
    payload: ContractorHoursCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Monthly hours worked per contractor company — the TRIR denominator
    (see ContractorHours model). Excel import writes this same table via
    _insert_contractor_hours; this is the single-record equivalent."""
    require_role(current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES, "log contractor hours")
    _get_company(db, payload.contractor_company_id, current_user.org_id)
    row = ContractorHours(organisation_id=current_user.org_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return ContractorHoursResponse.model_validate(row)


@router.get("/workers/by-badge/{badge_no}", response_model=ContractorWorkerResponse)
def worker_by_badge(
    badge_no: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """QR/badge scan on site — the roll-call lookup."""
    require_role(current_user.role, READ_ROLES, "look up a contractor worker")
    row = (
        db.query(ContractorWorker)
        .filter(ContractorWorker.badge_no == badge_no)
        .filter(ContractorWorker.organisation_id == current_user.org_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Contractor worker not found for that badge")
    return ContractorWorkerResponse.model_validate(row)


@router.post("/workers/{worker_id}/access", response_model=ContractorWorkerResponse)
def update_site_access(
    worker_id: int,
    payload: SiteAccessUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(
        current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES, "change contractor site access"
    )
    row = (
        db.query(ContractorWorker)
        .filter(ContractorWorker.id == worker_id)
        .filter(ContractorWorker.organisation_id == current_user.org_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Contractor worker not found")

    # Induction has to be current before access can be granted.
    if payload.site_access_status == "granted":
        if row.induction_valid_until and row.induction_valid_until < date.today():
            raise HTTPException(
                status_code=400,
                detail=f"Induction expired on {row.induction_valid_until} — cannot grant site access",
            )

    row.site_access_status = payload.site_access_status
    if payload.toolbox_completed:
        row.toolbox_completed_at = datetime.now()
    row.last_verified_at = datetime.now()
    db.commit()
    db.refresh(row)
    return ContractorWorkerResponse.model_validate(row)


# ══════════════════════════════════════════════════════════════════════════════
# Scorecards
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/scorecards/list", response_model=List[ScorecardResponse])
def list_scorecards(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, READ_ROLES, "view contractor scorecards")
    rows = (
        db.query(ContractorScorecard)
        .filter(ContractorScorecard.organisation_id == current_user.org_id)
        .order_by(ContractorScorecard.period_year.desc(), ContractorScorecard.period_quarter.desc())
        .all()
    )
    return [ScorecardResponse.model_validate(r) for r in rows]


@router.post("/scorecards/compute", response_model=List[ScorecardResponse])
def compute_scorecards(
    year: Optional[int] = None,
    quarter: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Quarterly: <50 enhanced oversight · <30 contract review · two quarters <30 = off list."""
    require_role(current_user.role, MANAGER_ROLES, "compute contractor scorecards")

    today = date.today()
    year = year or today.year
    quarter = quarter or ((today.month - 1) // 3 + 1)

    companies = (
        db.query(ContractorCompany)
        .filter(ContractorCompany.organisation_id == current_user.org_id)
        .all()
    )

    out: List[ContractorScorecard] = []
    for co in companies:
        scores = (
            db.query(RamsScore)
            .filter(RamsScore.contractor_company_id == co.id)
            .all()
        )
        avg_rams = round(sum(s.total_score for s in scores) / len(scores), 2) if scores else 0.0

        # Normalise the 0-120 RAMS average onto the 0-100 scorecard scale, then
        # subtract observed failures. Keeps the scorecard readable next to the
        # SPS, which is also 0-100.
        base = (avg_rams / 120 * 100) if scores else 50.0
        violations = sum(1 for s in scores if s.verdict == "reject")
        score = max(0.0, min(100.0, round(base - violations * 5, 2)))

        prior = (
            db.query(ContractorScorecard)
            .filter(ContractorScorecard.contractor_company_id == co.id)
            .filter(ContractorScorecard.period_year == (year if quarter > 1 else year - 1))
            .filter(ContractorScorecard.period_quarter == (quarter - 1 if quarter > 1 else 4))
            .first()
        )
        verdict = contractor_scorecard_verdict(
            score, float(prior.score) if prior else None
        )

        row = (
            db.query(ContractorScorecard)
            .filter(ContractorScorecard.contractor_company_id == co.id)
            .filter(ContractorScorecard.period_year == year)
            .filter(ContractorScorecard.period_quarter == quarter)
            .first()
        )
        if row is None:
            row = ContractorScorecard(
                organisation_id=current_user.org_id,
                contractor_company_id=co.id,
                period_year=year,
                period_quarter=quarter,
                source_system="server",
            )
            db.add(row)

        row.score = score
        row.avg_rams_score = avg_rams
        row.permit_violations = violations
        row.ltifr = co.ltifr_3yr
        row.verdict = verdict
        row.computed_at = datetime.now()
        row.last_verified_at = datetime.now()
        out.append(row)

    db.commit()
    for r in out:
        db.refresh(r)
    return [ScorecardResponse.model_validate(r) for r in out]


@router.post("/benchmarks", status_code=201)
def create_benchmark(
    payload: IogpBenchmarkCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, MANAGER_ROLES, "set an IOGP benchmark")
    row = IogpBenchmark(
        organisation_id=current_user.org_id,
        source_system="web",
        **payload.model_dump(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "benchmark_year": row.benchmark_year,
            "ltifr_benchmark": float(row.ltifr_benchmark)}


# ══════════════════════════════════════════════════════════════════════════════
# RAMS scoring  (/rams-scores)
# ══════════════════════════════════════════════════════════════════════════════
@rams_router.post("", response_model=RamsScoreResponse, status_code=201)
@rams_router.post("/", response_model=RamsScoreResponse, status_code=201)
def score_rams(
    payload: RamsScoreCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Supervisor scores a contractor method statement on the 6-criterion rubric."""
    require_role(current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES, "score a RAMS")

    criteria = {k: getattr(payload, k) for k in RAMS_CRITERIA}
    result = rams_score(**criteria)

    row = RamsScore(
        organisation_id=current_user.org_id,
        contractor_company_id=payload.contractor_company_id,
        permit_id=payload.permit_id,
        risk_report_id=payload.risk_report_id,
        task_description=payload.task_description,
        total_score=result.total_score,
        verdict=result.verdict,
        scored_by=employee_id_for(db, current_user.user_id),
        scored_at=datetime.now(),
        source_system="mobile",
        last_verified_at=datetime.now(),
        **criteria,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return RamsScoreResponse.model_validate(row)


@rams_router.get("", response_model=List[RamsScoreResponse])
@rams_router.get("/", response_model=List[RamsScoreResponse])
def list_rams(
    contractor_company_id: Optional[int] = None,
    permit_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    q = db.query(RamsScore).filter(RamsScore.organisation_id == current_user.org_id)
    if contractor_company_id:
        q = q.filter(RamsScore.contractor_company_id == contractor_company_id)
    if permit_id:
        q = q.filter(RamsScore.permit_id == permit_id)
    return [RamsScoreResponse.model_validate(r) for r in q.order_by(RamsScore.id.desc()).all()]


@rams_router.post("/{score_id}/rescore", response_model=RamsScoreResponse)
def auditor_rescore(
    score_id: int,
    payload: RamsRescore,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Auditor independently re-scores against the same rubric.

    The original score is never altered — both numbers stay on the record, which
    is the point: the gap between them is the audit finding.
    """
    require_role(current_user.role, AUDITOR_ROLES, "independently re-score a RAMS")
    row = (
        db.query(RamsScore)
        .filter(RamsScore.id == score_id)
        .filter(RamsScore.organisation_id == current_user.org_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="RAMS score not found")

    criteria = {k: getattr(payload, k) for k in RAMS_CRITERIA}
    result = rams_score(**criteria)

    row.auditor_total_score = result.total_score
    row.auditor_rescored_by = employee_id_for(db, current_user.user_id)
    row.auditor_rescored_at = datetime.now()
    row.auditor_notes = payload.notes
    row.last_verified_at = datetime.now()
    db.commit()
    db.refresh(row)
    return RamsScoreResponse.model_validate(row)
