"""WF-07 · Safety Performance Scoring.

    manager     GET  /sps/score           weekly 0-100, five domain breakdown
    manager     POST /sps/compute         run the weekly batch, raise alerts
    manager     GET  /sps/alerts          delta >= 10 / band change / KPI red-line
    manager     POST /sps/alerts/{id}/ack raise a CAPA from the lookup table
    supervisor  GET  /sps/team            five domain sub-scores for own area
    worker      GET  /sps/my-score        personal Human Readiness contribution
    auditor     GET  /sps/data-quality    the Data Quality Gate

WF-07 lands last because it aggregates WF-06, WF-08 and WF-09. Every figure is
server-calculated — the interaction matrix marks SPS "no manual entry anywhere".
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
from app.models.capa_action import CapaAction
from app.models.competence import CompetenceGap
from app.models.fatigue import FatigueDeclaration
from app.models.sps import CapaLookup, SpsAlert, SpsSnapshot
from app.schemas.sps import (
    DataQualityResponse,
    DataQualityRow,
    MySafetyScoreResponse,
    SpsAlertAck,
    SpsAlertResponse,
    SpsDomainBreakdown,
    SpsScoreResponse,
    SpsSnapshotResponse,
)
from app.services.hse_formulae import (
    SPS_STALE_DAYS,
    SPS_WEIGHTS,
    safety_performance_score,
    sps_alerts_for,
    sps_band,
)
from app.services.sps_engine import compute_sps

router = APIRouter(prefix="/sps", tags=["Safety Performance Score"])

VIEW_ROLES = SUPERVISOR_ROLES | MANAGER_ROLES | AUDITOR_ROLES
DATA_SOURCES = (
    "training_records",
    "fatigue_declarations",
    "competence_matrix",
    "contractor_companies",
    "vehicles",
    "rams_scores",
    "journey_plans",
)


def _default_period() -> tuple:
    end = date.today()
    return end - timedelta(days=7), end


@router.get("/score", response_model=SpsScoreResponse)
def sps_score(
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    site_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Live SPS for the period. Never cached — recomputed from the records."""
    require_role(current_user.role, VIEW_ROLES, "view the Safety Performance Score")
    start, end = (period_start, period_end) if period_start and period_end else _default_period()

    result, detail = compute_sps(db, current_user.org_id, start, end, site_id)

    previous = (
        db.query(SpsSnapshot)
        .filter(SpsSnapshot.organisation_id == current_user.org_id)
        .filter(SpsSnapshot.scope == ("site" if site_id else "org"))
        .filter(SpsSnapshot.period_end < end)
        .order_by(SpsSnapshot.period_end.desc())
        .first()
    )

    return SpsScoreResponse(
        scope="site" if site_id else "org",
        site_id=site_id,
        period_start=start,
        period_end=end,
        sps=result.sps,
        band=result.band,
        domains=SpsDomainBreakdown(**detail["domains"]),
        weights=result.weights,
        stale_data_penalty=result.stale_data_penalty,
        data_completeness=result.data_completeness,
        explanation=result.explanation,
        inputs=detail["sources"],
        previous_sps=float(previous.sps) if previous else None,
        delta=round(result.sps - float(previous.sps), 2) if previous else None,
    )


@router.post("/compute", response_model=SpsSnapshotResponse)
def compute_and_store(
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    site_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """The weekly batch. Stores the snapshot and raises any alerts it triggers."""
    require_role(current_user.role, MANAGER_ROLES, "run the SPS batch")
    start, end = (period_start, period_end) if period_start and period_end else _default_period()

    result, detail = compute_sps(db, current_user.org_id, start, end, site_id)
    scope = "site" if site_id else "org"

    previous = (
        db.query(SpsSnapshot)
        .filter(SpsSnapshot.organisation_id == current_user.org_id)
        .filter(SpsSnapshot.scope == scope)
        .filter(SpsSnapshot.period_end < end)
        .order_by(SpsSnapshot.period_end.desc())
        .first()
    )

    snapshot = SpsSnapshot(
        organisation_id=current_user.org_id,
        site_id=site_id,
        scope=scope,
        period_start=start,
        period_end=end,
        hazard_exposure=detail["domains"]["hazard_exposure"],
        control_integrity=detail["domains"]["control_integrity"],
        work_discipline=detail["domains"]["work_discipline"],
        human_readiness=detail["domains"]["human_readiness"],
        org_health=detail["domains"]["org_health"],
        sps=result.sps,
        band=result.band,
        data_completeness=result.data_completeness,
        stale_data_penalty=result.stale_data_penalty,
        inputs=detail["sources"],
        computed_at=datetime.now(),
        source_system="server",
        last_verified_at=datetime.now(),
        confidence_score=result.data_completeness,
    )
    db.add(snapshot)
    db.flush()

    # Alerts: delta >= 10 pts/week, band change, KPI red-line.
    if previous:
        prior_result = safety_performance_score(
            float(previous.hazard_exposure),
            float(previous.control_integrity),
            float(previous.work_discipline),
            float(previous.human_readiness),
            float(previous.org_health),
        )
        for alert in sps_alerts_for(prior_result, result):
            lookups = (
                db.query(CapaLookup)
                .filter(CapaLookup.organisation_id == current_user.org_id)
                .filter(CapaLookup.trigger_type == "sps_alert")
                .limit(3)
                .all()
            )
            db.add(
                SpsAlert(
                    organisation_id=current_user.org_id,
                    sps_snapshot_id=snapshot.id,
                    site_id=site_id,
                    alert_type=alert["alert_type"],
                    delta=alert.get("delta"),
                    previous_band=alert.get("previous_band"),
                    new_band=alert.get("new_band"),
                    severity=alert.get("severity"),
                    message=alert.get("message"),
                    suggested_capa=[
                        {
                            "action": l.suggested_action,
                            "control_type": l.control_type,
                            "due_days": l.default_due_days,
                        }
                        for l in lookups
                    ],
                    source_system="server",
                )
            )

    db.commit()
    db.refresh(snapshot)
    return SpsSnapshotResponse.model_validate(snapshot)


@router.get("/history", response_model=List[SpsSnapshotResponse])
def history(
    limit: int = Query(26, ge=1, le=104),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, VIEW_ROLES, "view SPS history")
    rows = (
        db.query(SpsSnapshot)
        .filter(SpsSnapshot.organisation_id == current_user.org_id)
        .order_by(SpsSnapshot.period_end.desc())
        .limit(limit)
        .all()
    )
    return [SpsSnapshotResponse.model_validate(r) for r in rows]


@router.get("/alerts", response_model=List[SpsAlertResponse])
def alerts(
    unacknowledged_only: bool = True,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, VIEW_ROLES, "view SPS alerts")
    q = db.query(SpsAlert).filter(SpsAlert.organisation_id == current_user.org_id)
    if unacknowledged_only:
        q = q.filter(SpsAlert.acknowledged_at.is_(None))
    return [SpsAlertResponse.model_validate(r) for r in q.order_by(SpsAlert.id.desc()).all()]


@router.post("/alerts/{alert_id}/ack", response_model=SpsAlertResponse)
def acknowledge_alert(
    alert_id: int,
    payload: SpsAlertAck,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Acknowledge, and optionally raise a CAPA straight from the lookup."""
    require_role(current_user.role, MANAGER_ROLES | SUPERVISOR_ROLES, "acknowledge an SPS alert")
    row = (
        db.query(SpsAlert)
        .filter(SpsAlert.id == alert_id)
        .filter(SpsAlert.organisation_id == current_user.org_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="SPS alert not found")

    row.acknowledged_by = employee_id_for(db, current_user.user_id)
    row.acknowledged_at = datetime.now()

    if payload.create_capa:
        description = payload.capa_description or (row.message or "SPS alert corrective action")
        # `action_description` is not a column on CapaAction and never has been,
        # so this raised TypeError and returned a 500 on every acknowledgement
        # that asked for a CAPA. The column is `description`.
        capa = CapaAction(
            organisation_id=current_user.org_id,
            description=description,
            # An SPS alert is a proactive signal rather than a reported event, so
            # it has no subject record — but it does have a source, without which
            # the action would be indistinguishable from the orphans the generic
            # CRUD endpoint produces.
            source="proactive",
            action_type="Preventive",
            root_cause_addressed=row.message,
            raised_by=employee_id_for(db, current_user.user_id),
            due_date=date.today() + timedelta(days=payload.due_days),
            status="Open",
        )
        db.add(capa)
        db.flush()
        capa.capa_ref = f"CAPA-{capa.id:06d}"
        row.capa_action_id = capa.id

    db.commit()
    db.refresh(row)
    return SpsAlertResponse.model_validate(row)


@router.get("/team", response_model=SpsScoreResponse)
def team_sps(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Supervisor's five domain sub-scores for their own area, with red-line KPIs."""
    require_role(current_user.role, VIEW_ROLES, "view the team SPS")
    return sps_score(db=db, current_user=current_user)


@router.get("/my-score", response_model=MySafetyScoreResponse)
def my_safety_score(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """The worker's own Human Readiness contribution.

    Deliberately scoped to this person's own competence gaps and fatigue flags.
    A worker never sees a colleague's score, and no other domain is exposed here
    — the spec gives the worker "My Safety Score", not the site's.
    """
    emp_id = employee_id_for(db, current_user.user_id)
    if not emp_id:
        raise HTTPException(status_code=400, detail="No employee record linked to this user")

    gaps = (
        db.query(CompetenceGap)
        .filter(CompetenceGap.employee_id == emp_id)
        .filter(CompetenceGap.resolved_at.is_(None))
        .all()
    )
    critical = [g for g in gaps if g.is_safety_critical]

    latest = (
        db.query(FatigueDeclaration)
        .filter(FatigueDeclaration.employee_id == emp_id)
        .order_by(FatigueDeclaration.id.desc())
        .first()
    )

    gap_component = min(100.0, len(gaps) * 15 + len(critical) * 25)
    fatigue_component = float(latest.fatigue_index) * 4 if latest else 0.0
    readiness = round(min(100.0, gap_component * 0.6 + min(100.0, fatigue_component) * 0.4), 2)

    if critical:
        guidance = (
            f"{len(critical)} safety-critical requirement(s) are missing or expired. "
            "These block high-risk permits until renewed."
        )
    elif latest and latest.band == "block":
        guidance = "Fatigue index is at or above 20 — 8 h rest required before further work."
    elif gaps:
        guidance = f"{len(gaps)} training requirement(s) need attention."
    else:
        guidance = "Competence and fatigue are both within limits."

    return MySafetyScoreResponse(
        employee_id=emp_id,
        human_readiness=readiness,
        band=sps_band(readiness),
        open_competence_gaps=len(gaps),
        safety_critical_gaps=len(critical),
        latest_fatigue_index=float(latest.fatigue_index) if latest else None,
        latest_fatigue_band=latest.band if latest else None,
        blocked_tasks=[g.requirement_name for g in critical if g.requirement_name],
        guidance=guidance,
    )


@router.get("/data-quality", response_model=DataQualityResponse)
def data_quality(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """The Data Quality Gate — any source >14 days stale is a Data Gap.

    "Stale feeds (>14 days) are penalised, not silently trusted."
    """
    require_role(current_user.role, AUDITOR_ROLES | MANAGER_ROLES, "run the data quality gate")
    now = datetime.now()
    rows: List[DataQualityRow] = []
    stale = 0

    for table in DATA_SOURCES:
        try:
            r = db.execute(
                text(
                    f"SELECT COUNT(*) AS c, MAX(COALESCE(last_verified_at, updated_at)) AS m "
                    f"FROM {table} WHERE organisation_id = :org"
                ),
                {"org": current_user.org_id},
            ).mappings().first()
        except Exception:
            continue

        count = int(r["c"] or 0)
        last = r["m"]
        days = (now - last).days if last else None
        is_gap = last is None or (days is not None and days > SPS_STALE_DAYS)
        if is_gap:
            stale += 1
        rows.append(
            DataQualityRow(
                source_table=table,
                last_verified_at=last,
                days_stale=days,
                is_data_gap=is_gap,
                record_count=count,
            )
        )

    return DataQualityResponse(
        stale_threshold_days=SPS_STALE_DAYS,
        stale_sources=stale,
        penalty_applied=10.0 if stale else 0.0,
        confidence_score=round(max(0.0, 100.0 - stale * 20), 2),
        rows=rows,
    )
