from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.utils.tenant import org_scoped_join
from app.models.capa_action import CapaAction
from app.models.employee import Employee
from app.models.hazard import Hazard
from app.models.hazard_category import HazardCategory
from app.models.incident import Incident
from app.models.audit import Audit
from app.models.near_miss import NearMiss
from app.models.permit_to_work import PermitToWork
from app.models.permit_type import PermitType
from app.models.risk_report import RiskReport
from app.models.unsafe_act import UnsafeAct
from app.models.safety_walk import SafetyWalk
from app.models.site import Site
from app.models.shift_schedule import ShiftSchedule
from app.models.working_station import WorkingStation
from app.services.audit_readiness import compute_audit_readiness
from app.services.contractor_risk import compute_contractor_risk, compute_contractor_safety_score

from app.utils.logger import get_logger
logger = get_logger(__name__)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def _org_filter(query, model, org_id):
    """Filter by org_id only. NULL organisation rows are not tenant data."""
    if org_id is not None:
        return query.filter(model.organisation_id == org_id)
    return query


def _date_filter(query, date_column, start_date: Optional[date], end_date: Optional[date]):
    """Apply optional start_date / end_date filter on a date or datetime column."""
    if start_date:
        query = query.filter(func.date(date_column) >= start_date)
    if end_date:
        query = query.filter(func.date(date_column) <= end_date)
    return query


def _latest_org_date(db: Session, model, date_column, org_id):
    latest_value = _org_filter(db.query(func.max(date_column)), model, org_id).scalar()
    return latest_value.date() if latest_value else None


def _org_data_anchor_date(db: Session, org_id) -> date:
    """The most recent date across this org's incidents/near-misses/safety
    walks — the real "as of" point for preset windows (7D/30D/90D/1Y).

    Anchoring on the real system clock instead breaks every preset whenever
    the org's actual data doesn't reach up to today (imported/demo data with
    older dates, or simply a clock running ahead of the last logged event):
    "last 7 days" would silently mean 7 days nothing was recorded in, not the
    7 most recent days of data. Falls back to today only when the org has no
    dated records at all yet, so a brand-new org's presets don't error.
    """
    candidates = [
        _latest_org_date(db, Incident, Incident.incident_date_time, org_id),
        _latest_org_date(db, NearMiss, NearMiss.event_date_time, org_id),
        _latest_org_date(db, SafetyWalk, SafetyWalk.inspection_date_time, org_id),
    ]
    dates = [d for d in candidates if d]
    return max(dates) if dates else date.today()


def _resolve_window(
    db: Session, org_id, start_date: Optional[date], end_date: Optional[date], days: Optional[int],
):
    """Turn a request's start_date/end_date/days into an effective (start, end).

    - Explicit start_date/end_date (the Custom picker) are respected as given;
      an open side of a custom range falls back to the data anchor, not
      real "today", for the same reason _org_data_anchor_date exists.
    - A bare `days` value (7/30/90/365 preset buttons) is resolved against
      the org's own latest recorded data via _org_data_anchor_date, not the
      real system clock.
    - Neither given ("All") returns (None, None) — no filter, true all-time.
    """
    if start_date or end_date:
        anchor = _org_data_anchor_date(db, org_id)
        return start_date, (end_date or anchor)
    if days:
        anchor = _org_data_anchor_date(db, org_id)
        return anchor - timedelta(days=days), anchor
    return None, None


def _safe_round(value, digits=2):
    return round(float(value), digits) if value is not None else 0.0


_CAPA_TERMINAL_STATUSES = ["completed", "closed", "verified", "done"]


def _capa_overdue_sql_filter(query, today: date):
    """A CAPA is overdue when its due date has passed and it hasn't reached a
    terminal status — the same rule app/services/capa_lifecycle.py's describe()
    uses for the per-row `is_overdue` flag shown everywhere else in the app.
    Older code here matched a literal status == "Overdue" instead, which was
    only ever true for the original demo dataset's pre-set status column —
    real due-date-driven data (freshly imported or newly created orgs) never
    writes that literal string, so the filter silently matched zero rows.
    """
    return query.filter(
        CapaAction.due_date.isnot(None),
        CapaAction.due_date < today,
        (CapaAction.status.is_(None)) | func.lower(CapaAction.status).notin_(_CAPA_TERMINAL_STATUSES),
    )


def _capa_is_overdue(status, due_date, today: date) -> bool:
    if not due_date or due_date >= today:
        return False
    return (status or "").strip().lower() not in _CAPA_TERMINAL_STATUSES


@router.get("/stats")
def get_dashboard_stats(
    start_date: Optional[date] = Query(None, description="Filter from date (YYYY-MM-DD) — Custom range"),
    end_date: Optional[date] = Query(None, description="Filter to date (YYYY-MM-DD) — Custom range"),
    days: Optional[int] = Query(None, description="Preset window (7/30/90/365), anchored on the org's own latest recorded data, not the real system clock"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    org_id = current_user.org_id
    start_date, end_date = _resolve_window(db, org_id, start_date, end_date, days)

    def inc_q():
        return _date_filter(_org_filter(db.query(Incident), Incident, org_id), Incident.incident_date_time, start_date, end_date)

    def nm_q():
        return _date_filter(_org_filter(db.query(NearMiss), NearMiss, org_id), NearMiss.event_date_time, start_date, end_date)

    def sw_q():
        return _date_filter(_org_filter(db.query(SafetyWalk), SafetyWalk, org_id), SafetyWalk.inspection_date_time, start_date, end_date)

    def capa_q():
        return _date_filter(_org_filter(db.query(CapaAction), CapaAction, org_id), CapaAction.due_date, start_date, end_date)

    total_incidents = inc_q().count()
    # Filtered on due_date within the selected period, same as every other
    # count on this card — previously org-wide regardless of period, which
    # disagreed with the CAPA list widgets below it once those became
    # period-aware.
    open_capa_actions = capa_q().filter(
        (CapaAction.status.is_(None)) | func.lower(CapaAction.status).notin_(["completed", "closed", "verified", "done"])
    ).count()
    overdue_capa = _capa_overdue_sql_filter(capa_q(), date.today()).count()
    active_permits = _org_filter(db.query(PermitToWork), PermitToWork, org_id).filter(PermitToWork.status == "Active").count()
    total_employees = _org_filter(db.query(Employee), Employee, org_id).count()
    total_sites = _org_filter(db.query(Site), Site, org_id).count()
    near_misses_count = nm_q().count()
    safety_walks_count = sw_q().count()
    # Worker-submitted risk reports and unsafe acts live in their own tables so they
    # surface on the web dashboard without being conflated with the incident register.
    risk_reports_count = _org_filter(db.query(RiskReport), RiskReport, org_id).count()
    unsafe_acts_count = _org_filter(db.query(UnsafeAct), UnsafeAct, org_id).count()

    avg_compliance = sw_q().with_entities(func.avg(SafetyWalk.compliance_rating)).scalar()
    avg_housekeeping = sw_q().with_entities(func.avg(SafetyWalk.housekeeping_rating)).scalar()

    # "Critical" is not an actual severity value in this schema (real values are
    # Fatal/Serious/Significant/Minor/Moderate/Lost Time) — count the genuinely
    # severe tiers instead of a label that never matches.
    critical_incidents = inc_q().filter(
        func.lower(Incident.severity).in_(["fatal", "serious", "significant"])
    ).count()

    # capa_completion_rate is org-wide (not date filtered) — it's a point-in-time health metric
    capa_completed = _org_filter(db.query(CapaAction), CapaAction, org_id).filter(
        func.lower(CapaAction.status).in_(["completed", "closed", "verified", "done"])
    ).count()
    capa_total = _org_filter(db.query(CapaAction), CapaAction, org_id).count()
    capa_completion_rate = round((capa_completed / capa_total * 100) if capa_total else 0, 1)

    return {
        "total_incidents": total_incidents,
        "open_capa_actions": open_capa_actions,
        "overdue_capa": overdue_capa,
        "active_permits": active_permits,
        "total_employees": total_employees,
        "total_sites": total_sites,
        "near_misses_count": near_misses_count,
        "safety_walks_count": safety_walks_count,
        "risk_reports_count": risk_reports_count,
        "unsafe_acts_count": unsafe_acts_count,
        "avg_compliance_rating": round(float(avg_compliance), 1) if avg_compliance else 0,
        "avg_housekeeping_rating": round(float(avg_housekeeping), 1) if avg_housekeeping else 0,
        "critical_incidents": critical_incidents,
        "capa_completion_rate": capa_completion_rate,
        # The window actually applied above (after resolving days/Custom against
        # the org's data) — the frontend reads this to label the period instead
        # of re-deriving it from the real client clock, which is exactly the
        # mismatch this endpoint now corrects for.
        "period_start": start_date.isoformat() if start_date else None,
        "period_end": end_date.isoformat() if end_date else None,
    }


@router.get("/leading-indicators")
def get_leading_indicators(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    days: Optional[int] = Query(None, description="Preset window (7/30/90/365), anchored on the org's own latest recorded data, not the real system clock"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Predictive/leading safety KPIs derived from incidents, employees and safety_walks.

    These are best-effort approximations (documented inline) since the schema does not
    track actual hours-worked or formal audit records. They move with real data but are
    not certified OSHA-audited figures.
    """
    org_id = current_user.org_id

    total_employees = _org_filter(db.query(Employee), Employee, org_id).count() or 0

    # ── Anchor dates on actual data, not today ───────────────────────────────
    # Using today as anchor makes all 90-day windows empty when historical data
    # is from a past year (or, same effect, the system clock has moved on past
    # the newest data). Anchor on the org's latest incident/near-miss/safety-
    # walk date instead — same anchor _resolve_window uses for the other
    # dashboard endpoints, so every tile driven by the same period selection
    # lands on the same effective window.
    #
    # near_miss_ratio divides near misses by recordable incidents over this
    # window. Ending it at the last incident capped the numerator there while
    # near misses kept arriving — every one reported from the mobile app
    # since the last incident fell outside the window, so the tile sat frozen
    # no matter how many were logged. That is the opposite of what a
    # *leading* indicator is for: near-miss reporting is supposed to move
    # before the next incident does, not wait for one.
    data_anchor = _org_data_anchor_date(db, org_id)

    if start_date or end_date:
        # Custom range — an open end falls back to the data anchor rather
        # than real "today", for the same reason the other two branches do.
        data_window_end = end_date or data_anchor
        data_window_start = start_date or None
    elif days:
        # Preset button (7D/30D/90D/1Y) — anchor on the org's own latest
        # recorded data instead of the real system clock, so "last 7 days"
        # means the 7 most recent days of data, not 7 days that happen to
        # contain nothing because the clock has drifted past the data.
        data_window_end = data_anchor
        data_window_start = data_anchor - timedelta(days=days)
    else:
        # "All" — extending the end date to the data anchor keeps both sides
        # of near_miss_ratio on the same window, so the methodology is
        # unchanged; the denominator simply has no incidents in the
        # extension, which is precisely the good news the ratio is meant to
        # show.
        data_window_end = data_anchor
        data_window_start = None

    latest_date = data_window_end

    # man_hours is the denominator for TRIR/LTIF/DART/FAR below — it must be
    # windowed the same way the incident numerators are, or a 7D/30D/90D
    # selection understates every rate against the all-time hours total.
    man_hours_base = _org_filter(db.query(func.coalesce(func.sum(ShiftSchedule.actual_hours_worked), 0.0)), ShiftSchedule, org_id)
    if data_window_start:
        man_hours_base = man_hours_base.filter(ShiftSchedule.shift_date >= data_window_start)
    if data_window_end:
        man_hours_base = man_hours_base.filter(ShiftSchedule.shift_date <= data_window_end)
    man_hours = man_hours_base.scalar() or 0.0

    # Workbook formulas are based on the full supplied dataset, not a rolling window.
    inc_base = _org_filter(db.query(Incident), Incident, org_id)
    if data_window_start:
        inc_base = inc_base.filter(func.date(Incident.incident_date_time) >= data_window_start)
    if data_window_end:
        inc_base = inc_base.filter(func.date(Incident.incident_date_time) <= data_window_end)

    recordable_incidents = inc_base.filter(
        func.lower(func.coalesce(Incident.incident_type, "")).in_(["injury"]),
    ).count()
    lost_time_incidents = inc_base.filter(
        func.lower(func.coalesce(Incident.incident_type, "")).in_(["injury"]),
        func.lower(func.coalesce(Incident.severity, "")).in_(["lost time"]),
    ).count()
    lost_days = inc_base.with_entities(
        func.coalesce(func.sum(func.coalesce(Incident.days_away, 0)), 0)
    ).filter(
        func.lower(func.coalesce(Incident.incident_type, "")).in_(["injury"]),
        func.lower(func.coalesce(Incident.severity, "")).in_(["lost time"]),
    ).scalar() or 0
    fatalities = inc_base.filter(
        func.lower(func.coalesce(Incident.severity, "")).in_(["fatal"]),
    ).count()
    near_miss_count = _date_filter(
        _org_filter(db.query(NearMiss), NearMiss, org_id),
        NearMiss.event_date_time, data_window_start, data_window_end
    ).count()
    total_investigations = inc_base.count()
    completed_investigations = inc_base.filter(
        func.lower(func.coalesce(Incident.investigation_status, "")).in_(["completed"]),
    ).count()

    trir = _safe_round((recordable_incidents * 200_000) / man_hours) if man_hours else 0.0
    ltifr = _safe_round((lost_time_incidents * 1_000_000) / man_hours) if man_hours else 0.0
    ltisr = _safe_round((float(lost_days) * 1_000_000) / man_hours) if man_hours else 0.0
    dart_rate = _safe_round((lost_time_incidents * 200_000) / man_hours) if man_hours else 0.0
    far = _safe_round((fatalities * 100_000_000) / man_hours) if man_hours else 0.0
    near_miss_ratio = _safe_round(near_miss_count / recordable_incidents, 1) if recordable_incidents else 0.0

    latest_lti_date = _org_filter(db.query(func.max(Incident.incident_date_time)), Incident, org_id).filter(
        func.lower(func.coalesce(Incident.incident_type, "")).in_(["injury"]),
        func.lower(func.coalesce(Incident.severity, "")).in_(["lost time"]),
    ).scalar()

    safe_days = int((data_window_end - latest_lti_date.date()).days) if latest_lti_date else 0
    dangerous_occurrence_rate = _org_filter(db.query(Incident), Incident, org_id).filter(
        func.lower(func.coalesce(Incident.incident_type, "")).in_(["dangerous occurrence"]),
    ).count()
    incident_close_out_rate = _safe_round((completed_investigations / total_investigations) * 100) if total_investigations else 0.0

    # ── Predictive Injury Risk Score ────────────────────────────────────────
    # Weighted by actual severity values in this schema (Fatal/Serious/Significant/
    # Lost Time/Moderate/Minor) — the previous "critical"/"high"/"major" labels don't
    # exist in the data, so Fatal and Serious incidents were silently falling into the
    # lowest-weight bucket instead of the highest. Max weight stays 3 to match the
    # existing (count * 3) normalization below.
    severity_weight = case(
        (func.lower(Incident.severity) == "fatal", 3),
        (func.lower(Incident.severity) == "serious", 2.5),
        (func.lower(Incident.severity) == "significant", 2),
        (func.lower(Incident.severity) == "lost time", 1.5),
        (func.lower(Incident.severity) == "moderate", 1),
        else_=0.5,
    )

    def weighted_risk_score(start_date, end_date, inclusive_end: bool = False):
        # inclusive_end=True for the "current" window: end_date is anchored on the
        # latest incident's own date (see latest_date above), so a strict `<` would
        # exclude that incident from its own window — e.g. right after a worker
        # submits a same-day report, the score would drop to 0 instead of reflecting
        # it. The "previous" window keeps the exclusive bound so the two windows
        # don't double-count incidents dated exactly on the current_start boundary.
        #
        # Returns (score, count, weight_sum) — count/weight_sum are the exact
        # inputs the score was computed from, surfaced for the dashboard's Info
        # tooltip so it can show the real numbers instead of re-deriving them.
        q = (
            _org_filter(
                db.query(
                    func.count(Incident.id).label("count"),
                    func.coalesce(func.sum(severity_weight), 0).label("weight_sum"),
                ),
                Incident,
                org_id,
            )
            .filter(Incident.incident_date_time.isnot(None))
            .filter(func.date(Incident.incident_date_time) >= start_date)
        )
        q = q.filter(func.date(Incident.incident_date_time) <= end_date) if inclusive_end else q.filter(
            func.date(Incident.incident_date_time) < end_date
        )
        row = q.first()
        count = int(row.count or 0)
        weight_sum = float(row.weight_sum or 0)
        if not count:
            return 0.0, count, weight_sum
        return min(100.0, (weight_sum / (count * 3)) * 100), count, weight_sum

    # The comparison window tracks whatever period the user actually selected
    # (7D/30D/90D/1Y/custom) rather than always being a fixed 90 days — a 7-day
    # selection was previously still scored and trended over 90-day windows, so
    # the trend arrow answered a different question from the one the period
    # picker asked. "Previous" is the immediately preceding window of the same
    # length, per the client's own correction: not "vs last year", the
    # corresponding prior period for whatever range is on screen.
    #
    # When no period is selected ("All"), data_window_start is None and there
    # is no user-chosen range to mirror, so the comparison falls back to a
    # fixed 90-day window — same fallback the rest of this function already
    # uses for data_window_end's anchor.
    period_days = max(1, (data_window_end - data_window_start).days) if data_window_start else 90
    current_start = latest_date - timedelta(days=period_days)
    previous_start = latest_date - timedelta(days=period_days * 2)
    current_score, current_incident_count, current_weight_sum = weighted_risk_score(
        current_start, latest_date, inclusive_end=True
    )
    previous_score, previous_incident_count, previous_weight_sum = weighted_risk_score(
        previous_start, current_start
    )
    injury_risk_score = _safe_round(current_score)
    injury_risk_trend = _safe_round(current_score - previous_score)

    # ── Contractor Risk Score — single shared implementation, see app/services/contractor_risk.py
    permanent_employees = _org_filter(db.query(Employee), Employee, org_id).filter(
        func.lower(Employee.employment_type) == "permanent"
    ).count()
    permanent_incidents = (
        _org_filter(
            db.query(func.count(Incident.id)),
            Incident,
            org_id,
        )
        .join(Employee, org_scoped_join(Incident.reported_by == Employee.id, Employee.organisation_id, org_id))
        .filter(func.lower(Employee.employment_type) == "permanent")
        .scalar()
        or 0
    )

    contractor_risk = compute_contractor_risk(db, org_id)
    contractor_employees = contractor_risk.contractor_employees
    contractor_incidents = contractor_risk.contractor_incidents
    contractor_rate = _safe_round(contractor_incidents / contractor_employees) if contractor_employees else 0.0
    permanent_rate = _safe_round(permanent_incidents / permanent_employees) if permanent_employees else 0.0

    contractor_risk_score_10 = contractor_risk.score_10
    contractor_risk_score = contractor_risk.score_pct
    contractor_risk_label = contractor_risk.label
    relative_risk = contractor_risk.relative_risk
    logger.info("CONTRACTOR_RISK: score_10=%s score_pct=%s label=%s violations=%s has_contractors=%s",
                contractor_risk_score_10, contractor_risk_score, contractor_risk_label,
                contractor_risk.contractor_violations, contractor_risk.has_contractors)

    # ── Contractor Safety Score — same shared implementation as the Vendors
    # page's Safety Score KPI (app/services/contractor_risk.py) ─────────────
    contractor_safety = compute_contractor_safety_score(db, org_id)

    # ── Audit Readiness Score — single shared implementation, see
    # app/services/audit_readiness.py (same all-time score as the Compliance
    # page, deliberately not windowed to the selected period) ──────────────
    audit_readiness = compute_audit_readiness(db, org_id)
    audit_readiness_score = audit_readiness.score
    audit_readiness_label = audit_readiness.label

    return {
        "predictive_injury_risk_score": injury_risk_score,
        "predictive_injury_risk_previous_score": _safe_round(previous_score),
        "predictive_injury_risk_trend": injury_risk_trend,
        # Raw inputs behind the two scores above, for the KPI's Info tooltip —
        # same weighted_risk_score() calls, not a separate/re-derived figure.
        "predictive_injury_risk_detail": {
            "current_window_start": current_start.isoformat(),
            "current_window_end": latest_date.isoformat(),
            "previous_window_start": previous_start.isoformat(),
            "previous_window_end": current_start.isoformat(),
            "period_days": period_days,
            "period_source": (
                "custom" if (start_date or end_date)
                else "preset_anchor" if days
                else "default_90d"
            ),
            "current_incident_count": current_incident_count,
            "current_weight_sum": round(current_weight_sum, 2),
            "previous_incident_count": previous_incident_count,
            "previous_weight_sum": round(previous_weight_sum, 2),
        },
        "trir": trir,
        "ltifr": ltifr,
        "ltisr": ltisr,
        "dart_rate": dart_rate,
        "far": far,
        "near_miss_ratio": near_miss_ratio,
        "safe_days": safe_days,
        "dangerous_occurrence_rate": dangerous_occurrence_rate,
        "incident_close_out_rate": incident_close_out_rate,
        "ltif": ltifr,
        "contractor_risk_label": contractor_risk_label,
        "contractor_rate": contractor_rate,
        "permanent_rate": permanent_rate,
        "relative_risk": relative_risk,
        "contractor_risk_score": contractor_risk_score,
        "contractor_risk_score_10": contractor_risk_score_10,
        "contractor_has_contractors": contractor_risk.has_contractors,
        "contractor_safety_score": contractor_safety.score,
        "contractor_safety_company_count": contractor_safety.company_count,
        "audit_readiness_score": audit_readiness_score,
        "audit_readiness_label": audit_readiness_label,
    }


@router.get("/contractor-debug")
def get_contractor_debug(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Debug endpoint to verify contractor risk score calculation."""
    org_id = current_user.org_id
    r = compute_contractor_risk(db, org_id)
    return {
        "has_contractors": r.has_contractors,
        "contractor_employees": r.contractor_employees,
        "total_employees": r.total_employees,
        "contractor_incidents": r.contractor_incidents,
        "total_org_incidents": r.total_org_incidents,
        "contractor_violations": r.contractor_violations,
        "relative_risk": r.relative_risk,
        "incident_penalty": r.incident_penalty,
        "violation_penalty": r.violation_penalty,
        "score_10": r.score_10,
        "score_pct": r.score_pct,
        "label": r.label,
    }


@router.get("/capa-actions")
def get_ranked_capa_actions(
    limit: int = Query(10, le=1000),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    days: Optional[int] = Query(None, description="Preset window (7/30/90/365), anchored on the org's own latest recorded data, not the real system clock"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    org_id = current_user.org_id
    start_date, end_date = _resolve_window(db, org_id, start_date, end_date, days)
    q = _org_filter(db.query(CapaAction, Employee), CapaAction, org_id)\
        .outerjoin(Employee, org_scoped_join(CapaAction.responsible_person_id == Employee.id, Employee.organisation_id, org_id))\
        .filter((CapaAction.status.is_(None)) | func.lower(CapaAction.status).notin_(["completed", "closed", "verified", "done"]))
    if start_date:
        q = q.filter(func.date(CapaAction.due_date) >= start_date)
    if end_date:
        q = q.filter(func.date(CapaAction.due_date) <= end_date)
    rows = q.order_by(case((CapaAction.due_date.is_(None), 1), else_=0), CapaAction.due_date.asc()).limit(limit).all()
    today = date.today()
    result = []
    for capa, emp in rows:
        is_overdue = _capa_is_overdue(capa.status, capa.due_date, today)
        result.append({
            "id": capa.id,
            "description": capa.description,
            "action_type": capa.action_type,
            "root_cause_addressed": capa.root_cause_addressed,
            "status": capa.status,
            "due_date": capa.due_date.isoformat() if capa.due_date else None,
            "is_overdue": is_overdue,
            "incident_id": capa.incident_id,
            "assignee": emp.full_name if emp else "Unassigned",
            "priority": "High" if is_overdue else ("Medium" if capa.status == "In Progress" else "Low"),
        })
    return result


@router.get("/overdue-capa")
def get_overdue_capa(
    limit: int = Query(10, le=1000),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    days: Optional[int] = Query(None, description="Preset window (7/30/90/365), anchored on the org's own latest recorded data, not the real system clock"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    org_id = current_user.org_id
    today = date.today()
    start_date, end_date = _resolve_window(db, org_id, start_date, end_date, days)
    rows = (
        _date_filter(
            _capa_overdue_sql_filter(_org_filter(db.query(CapaAction), CapaAction, org_id), today),
            CapaAction.due_date, start_date, end_date,
        )
        .order_by(CapaAction.due_date.asc())
        .limit(limit)
        .all()
    )
    result = []
    for c in rows:
        days_overdue = max(0, (today - c.due_date).days) if c.due_date else 0
        result.append({
            "id": c.id,
            "incident_id": c.incident_id,
            "description": c.description,
            "action_type": c.action_type,
            "status": c.status,
            "due_date": c.due_date.isoformat() if c.due_date else None,
            "days_overdue": days_overdue,
            "label": f"Incident #{c.incident_id} - {c.action_type or 'Action'} - {days_overdue} Day{'s' if days_overdue != 1 else ''} Overdue",
        })
    return result


@router.get("/incidents-by-category")
def get_incidents_by_category(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    days: Optional[int] = Query(None, description="Preset window (7/30/90/365), anchored on the org's own latest recorded data, not the real system clock"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    org_id = current_user.org_id
    start_date, end_date = _resolve_window(db, org_id, start_date, end_date, days)
    # HazardCategory and Hazard are themselves org-owned (each org can define its
    # own categories/hazards), and hazard_id/category_id are global-PK foreign
    # keys — an unscoped join can pull another org's category name or hazard
    # into this org's incident count. Every hop is constrained to org_id.
    inc_q = _org_filter(db.query(
            HazardCategory.category_name,
            func.count(Incident.id).label("count"),
        ), HazardCategory, org_id) \
        .outerjoin(Hazard, org_scoped_join(Hazard.category_id == HazardCategory.id, Hazard.organisation_id, org_id)) \
        .outerjoin(Incident, org_scoped_join(Incident.hazard_id == Hazard.id, Incident.organisation_id, org_id)) \
        .filter(Incident.organisation_id == org_id if org_id is not None else True)
    if start_date:
        inc_q = inc_q.filter(func.date(Incident.incident_date_time) >= start_date)
    if end_date:
        inc_q = inc_q.filter(func.date(Incident.incident_date_time) <= end_date)
    rows = inc_q.group_by(HazardCategory.category_name)\
                .order_by(func.count(Incident.id).desc())\
                .limit(8).all()
    return [{"name": r.category_name, "data": r.count} for r in rows]


@router.get("/incidents-by-severity")
def get_incidents_by_severity(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    org_id = current_user.org_id
    rows = (
        _org_filter(db.query(Incident.severity, func.count(Incident.id).label("count")), Incident, org_id)
        .filter(Incident.severity.isnot(None))
        .group_by(Incident.severity)
        .all()
    )
    return [{"severity": r.severity, "count": r.count} for r in rows]


@router.get("/compliance-trend")
def get_compliance_trend(
    days: int = 30,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    org_id = current_user.org_id
    latest_walk_dt = _org_filter(db.query(func.max(SafetyWalk.inspection_date_time)), SafetyWalk, org_id).scalar()
    anchor = latest_walk_dt.date() if latest_walk_dt else date.today()
    cutoff = anchor - timedelta(days=days)
    rows = (
        _org_filter(
            db.query(
                func.date(SafetyWalk.inspection_date_time).label("day"),
                func.avg(SafetyWalk.compliance_rating).label("avg_score"),
            ),
            SafetyWalk,
            org_id,
        )
        .filter(SafetyWalk.inspection_date_time.isnot(None))
        .filter(func.date(SafetyWalk.inspection_date_time) >= cutoff)
        .group_by(func.date(SafetyWalk.inspection_date_time))
        .order_by(func.date(SafetyWalk.inspection_date_time).asc())
        .all()
    )
    return [
        {"date": str(r.day), "score": round(float(r.avg_score) * 20, 1) if r.avg_score else 0}
        for r in rows
    ]


@router.get("/safety-walks-recent")
def get_safety_walks_recent(
    limit: int = Query(5, le=1000),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    days: Optional[int] = Query(None, description="Preset window (7/30/90/365), anchored on the org's own latest recorded data, not the real system clock"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    org_id = current_user.org_id
    start_date, end_date = _resolve_window(db, org_id, start_date, end_date, days)
    rows = (
        _date_filter(
            _org_filter(db.query(SafetyWalk, WorkingStation, Employee), SafetyWalk, org_id),
            SafetyWalk.inspection_date_time, start_date, end_date,
        )
        .outerjoin(WorkingStation, org_scoped_join(SafetyWalk.location_station_id == WorkingStation.id, WorkingStation.organisation_id, org_id))
        .outerjoin(Employee, org_scoped_join(SafetyWalk.inspector_id == Employee.id, Employee.organisation_id, org_id))
        .order_by(SafetyWalk.inspection_date_time.desc())
        .limit(limit)
        .all()
    )
    result = []
    for sw, ws, emp in rows:
        result.append({
            "id": sw.id,
            # DSW- per the client's own naming during the meeting review — no
            # stored ref column, computed the same way INC-{id:05d} is, so
            # there is exactly one source of truth for the number, not a
            # stored value that a second callsite can reformat differently.
            "reference": f"DSW-{sw.id:05d}",
            "inspection_date_time": sw.inspection_date_time.isoformat() if sw.inspection_date_time else None,
            "location": ws.station_name if ws else (f"Station {sw.location_station_id}" if sw.location_station_id else "Unknown"),
            "inspector": emp.full_name if emp else "Unknown",
            "inspection_type": sw.inspection_type,
            "issues_found": sw.issues_found or 0,
            "critical_issues": sw.critical_issues or 0,
            "compliance_rating": sw.compliance_rating,
            "follow_up_required": sw.follow_up_required,
            "priority": "Critical" if (sw.critical_issues or 0) > 0 else ("High" if (sw.issues_found or 0) > 2 else "Medium"),
        })
    return result


@router.get("/near-misses-recent")
def get_near_misses_recent(
    limit: int = Query(5, le=1000),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    days: Optional[int] = Query(None, description="Preset window (7/30/90/365), anchored on the org's own latest recorded data, not the real system clock"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    org_id = current_user.org_id
    start_date, end_date = _resolve_window(db, org_id, start_date, end_date, days)
    rows = (
        _date_filter(
            _org_filter(db.query(NearMiss, WorkingStation, Employee), NearMiss, org_id),
            NearMiss.event_date_time, start_date, end_date,
        )
        .outerjoin(WorkingStation, org_scoped_join(NearMiss.location_station_id == WorkingStation.id, WorkingStation.organisation_id, org_id))
        .outerjoin(Employee, org_scoped_join(NearMiss.reported_by == Employee.id, Employee.organisation_id, org_id))
        .order_by(NearMiss.event_date_time.desc())
        .limit(limit)
        .all()
    )
    result = []
    for nm, ws, emp in rows:
        result.append({
            "id": nm.id,
            # NEA-{id}, unpadded — matches report_trail_factory.py's own
            # ref_prefix="NEA" (near_miss_trail.py), the reference shown on
            # the actual Near Miss register/tracker pages. An earlier pass
            # here computed "NM-{id:05d}" instead, matching a naming example
            # floated in the client meeting but not the codebase's own
            # already-established convention — that just moved the same
            # cross-panel mismatch this is meant to fix rather than closing it.
            "reference": f"NEA-{nm.id}",
            "report_date": nm.report_date.isoformat() if nm.report_date else None,
            "event_date_time": nm.event_date_time.isoformat() if nm.event_date_time else None,
            "location": ws.station_name if ws else (f"Station {nm.location_station_id}" if nm.location_station_id else "Unknown"),
            "description": nm.description,
            "potential_consequence": nm.potential_consequence,
            "underlying_cause": nm.underlying_cause,
            "reporter": emp.full_name if emp else "Unknown",
            "capa_escalation": nm.capa_escalation,
            "severity": "High" if nm.potential_consequence and "fatal" in (nm.potential_consequence or "").lower() else "Medium",
        })
    return result


@router.get("/permits-active")
def get_active_permits(
    limit: int = Query(10, le=1000),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    org_id = current_user.org_id
    rows = (
        _org_filter(db.query(PermitToWork, PermitType, WorkingStation), PermitToWork, org_id)
        .outerjoin(PermitType, org_scoped_join(PermitToWork.permit_type_id == PermitType.id, PermitType.organisation_id, org_id))
        .outerjoin(WorkingStation, org_scoped_join(PermitToWork.location_station_id == WorkingStation.id, WorkingStation.organisation_id, org_id))
        .filter(PermitToWork.status == "Active")
        .order_by(PermitToWork.validity_end.asc())
        .limit(limit)
        .all()
    )
    result = []
    for ptw, pt, ws in rows:
        result.append({
            "id": ptw.id,
            "permit_ref": f"PTW-{ptw.id:04d}",
            "permit_type": pt.permit_type_name if pt else "Unknown",
            "location": ws.station_name if ws else (f"Station {ptw.location_station_id}" if ptw.location_station_id else "Unknown"),
            "work_description": ptw.work_description,
            "number_of_workers": ptw.number_of_workers,
            "validity_start": ptw.validity_start.isoformat() if ptw.validity_start else None,
            "validity_end": ptw.validity_end.isoformat() if ptw.validity_end else None,
            "status": ptw.status,
        })
    return result
