"""WF-07 · Safety Performance Score — the five leading-impact domains.

Each domain is built from leading indicators rather than injury counts, "so
risk is visible before harm occurs". Every domain returns 0-100 where higher
means worse, and every sub-metric states which field it came from so an auditor
can trace the number back to a record.

The domains are the same five PIRS uses. SPS measures where safety stands right
now with fixed published weights. PIRS estimates probability over 7/30/90 days
and is the AI counterpart — this module is the deterministic, auditable core.
"""
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.hse_formulae import (
    SPS_STALE_DAYS,
    SpsResult,
    safety_performance_score,
)


def _scalar(db: Session, sql: str, params: dict) -> float:
    """Run a scalar aggregate, tolerating deployments where a column is absent."""
    try:
        row = db.execute(text(sql), params).mappings().first()
        if not row:
            return 0.0
        value = list(row.values())[0]
        return float(value or 0)
    except Exception:
        return 0.0


def _pct(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return round(min(100.0, max(0.0, numerator / denominator * 100)), 2)


def compute_domains(
    db: Session,
    org_id: Optional[int],
    period_start: date,
    period_end: date,
    site_id: Optional[int] = None,
) -> dict:
    """The five domain scores plus the raw inputs each was built from."""
    # Half-open interval [start, end+1day). BETWEEN coerces a DATE bound to
    # midnight, which silently dropped every event recorded *today* — the
    # entire current shift was invisible to the live SPS.
    p = {
        "org": org_id,
        "start": period_start,
        "end_exclusive": period_end + timedelta(days=1),
    }
    inputs: dict = {}

    # ── 1 · Hazard Exposure ───────────────────────────────────────────────────
    # High-risk task frequency, hazard severity, and work without a valid
    # risk assessment. "A missing risk assessment applies an immediate penalty."
    high_energy = _scalar(
        db,
        "SELECT COUNT(*) FROM permits_to_work WHERE organisation_id=:org "
        "AND is_high_energy=1 AND date_issued >= :start AND date_issued < :end_exclusive",
        p,
    )
    permits_total = _scalar(
        db,
        "SELECT COUNT(*) FROM permits_to_work WHERE organisation_id=:org "
        "AND date_issued >= :start AND date_issued < :end_exclusive",
        p,
    )
    permits_no_rams = _scalar(
        db,
        "SELECT COUNT(*) FROM permits_to_work ptw WHERE ptw.organisation_id=:org "
        "AND ptw.date_issued >= :start AND ptw.date_issued < :end_exclusive "
        "AND NOT EXISTS (SELECT 1 FROM rams_scores r WHERE r.permit_id = ptw.id)",
        p,
    )
    open_hazards = _scalar(
        db,
        "SELECT COUNT(*) FROM hazards WHERE organisation_id=:org "
        "AND (register_status IS NULL OR register_status IN ('open','under_review'))",
        p,
    )

    hazard_exposure = round(
        0.4 * _pct(high_energy, max(permits_total, 1))
        + 0.4 * _pct(permits_no_rams, max(permits_total, 1))
        + 0.2 * min(100.0, open_hazards * 5),
        2,
    )
    inputs["hazard_exposure"] = {
        "high_energy_permits": high_energy,
        "permits_total": permits_total,
        "permits_without_risk_assessment": permits_no_rams,
        "open_hazards": open_hazards,
    }

    # ── 2 · Control Integrity ─────────────────────────────────────────────────
    # Permit condition violations, recurrence, corrective action effectiveness.
    capa_total = _scalar(
        db, "SELECT COUNT(*) FROM capa_actions WHERE organisation_id=:org", p
    )
    capa_overdue = _scalar(
        db,
        "SELECT COUNT(*) FROM capa_actions WHERE organisation_id=:org "
        "AND due_date < CURDATE() AND (status IS NULL OR status NOT IN ('Closed','Completed','Verified'))",
        p,
    )
    gate_blocks = _scalar(
        db,
        "SELECT COUNT(*) FROM gate_decision_log WHERE organisation_id=:org "
        "AND verdict='block' AND evaluated_at >= :start AND evaluated_at < :end_exclusive",
        p,
    )
    gate_total = _scalar(
        db,
        "SELECT COUNT(*) FROM gate_decision_log WHERE organisation_id=:org "
        "AND evaluated_at >= :start AND evaluated_at < :end_exclusive",
        p,
    )

    # WF-01: "heavy PPE reliance lowers the Control Integrity domain of the
    # safety score." PPE leaves the hazard fully intact, so a site whose
    # controls are mostly PPE has not controlled anything — it has issued
    # equipment and hoped. A domain that scores that the same as a site which
    # engineered its hazards out is not measuring control integrity.
    #
    # A third of the weight, alongside overdue CAPAs and gate blocks: it is a
    # real signal about the quality of control, not the whole story.
    ppe_only = _scalar(
        db,
        "SELECT COUNT(*) FROM hazards WHERE organisation_id=:org "
        "AND LOWER(COALESCE(control_hierarchy,''))='ppe'",
        p,
    )
    controlled_total = _scalar(
        db,
        "SELECT COUNT(*) FROM hazards WHERE organisation_id=:org "
        "AND COALESCE(control_hierarchy,'') <> ''",
        p,
    )
    ppe_reliance = _pct(ppe_only, max(controlled_total, 1))

    control_integrity = round(
        (_pct(capa_overdue, max(capa_total, 1))
         + _pct(gate_blocks, max(gate_total, 1))
         + ppe_reliance) / 3,
        2,
    )
    inputs["control_integrity"] = {
        "capa_total": capa_total,
        "capa_overdue": capa_overdue,
        "ppe_only_controls": ppe_only,
        "controls_with_a_hierarchy": controlled_total,
        "ppe_reliance_pct": ppe_reliance,
        "gate_blocks": gate_blocks,
        "gate_evaluations": gate_total,
    }

    # ── 3 · Work Authorisation & Discipline ───────────────────────────────────
    # Permit bypass rate, closure quality, toolbox completion.
    overrides = _scalar(
        db,
        "SELECT COUNT(*) FROM override_log WHERE organisation_id=:org "
        "AND overridden_at >= :start AND overridden_at < :end_exclusive",
        p,
    )
    bypass_events = _scalar(
        db,
        "SELECT COUNT(*) FROM work_execution_events WHERE organisation_id=:org "
        "AND event_type IN ('permit_bypass','late_closure','poor_closure','repeat_breach') "
        "AND occurred_at >= :start AND occurred_at < :end_exclusive",
        p,
    )
    toolbox = _scalar(
        db,
        "SELECT COUNT(*) FROM supervisor_interactions WHERE organisation_id=:org "
        "AND interaction_type='toolbox_talk' AND occurred_at >= :start AND occurred_at < :end_exclusive",
        p,
    )
    headcount = _scalar(db, "SELECT COUNT(*) FROM employees WHERE organisation_id=:org", p)

    # Expect roughly one toolbox talk per 10 workers per period.
    expected_toolbox = max(1.0, headcount / 10.0)
    toolbox_shortfall = _pct(max(0.0, expected_toolbox - toolbox), expected_toolbox)

    work_discipline = round(
        0.4 * _pct(overrides, max(gate_total, 1))
        + 0.3 * min(100.0, bypass_events * 10)
        + 0.3 * toolbox_shortfall,
        2,
    )
    inputs["work_discipline"] = {
        "gate_overrides": overrides,
        "bypass_events": bypass_events,
        "toolbox_talks": toolbox,
        "toolbox_expected": round(expected_toolbox, 1),
    }

    # ── 4 · Human Readiness & Capacity ────────────────────────────────────────
    # Competence gaps, fatigue, exposure of new or inexperienced workers.
    # "Fatigue combined with a competence gap produces a step change."
    gaps = _scalar(
        db,
        "SELECT COUNT(*) FROM competence_gaps WHERE organisation_id=:org AND resolved_at IS NULL",
        p,
    )
    critical_gaps = _scalar(
        db,
        "SELECT COUNT(*) FROM competence_gaps WHERE organisation_id=:org "
        "AND resolved_at IS NULL AND is_safety_critical=1",
        p,
    )
    fatigue_flagged = _scalar(
        db,
        "SELECT COUNT(*) FROM fatigue_declarations WHERE organisation_id=:org "
        "AND band <> 'acceptable' AND declared_at >= :start AND declared_at < :end_exclusive",
        p,
    )
    fatigue_total = _scalar(
        db,
        "SELECT COUNT(*) FROM fatigue_declarations WHERE organisation_id=:org "
        "AND declared_at >= :start AND declared_at < :end_exclusive",
        p,
    )

    gap_rate = _pct(gaps, max(headcount, 1))
    fatigue_rate = _pct(fatigue_flagged, max(fatigue_total, 1))
    human_readiness = round(
        0.35 * gap_rate
        + 0.25 * min(100.0, critical_gaps * 20)
        + 0.40 * fatigue_rate,
        2,
    )
    # The multiplicative step change the spec calls for: fatigue on top of a
    # competence gap is worse than either alone, not merely their sum.
    if gap_rate > 0 and fatigue_rate > 0:
        human_readiness = round(min(100.0, human_readiness * 1.25), 2)

    inputs["human_readiness"] = {
        "open_competence_gaps": gaps,
        "safety_critical_gaps": critical_gaps,
        "fatigue_declarations": fatigue_total,
        "fatigue_flagged": fatigue_flagged,
        "headcount": headcount,
        "step_change_applied": gap_rate > 0 and fatigue_rate > 0,
    }

    # ── 5 · Organisational & System Health ────────────────────────────────────
    # Near-miss to injury ratio, CAPA ageing, supervisor engagement.
    incidents = _scalar(
        db,
        "SELECT COUNT(*) FROM incidents WHERE organisation_id=:org "
        "AND created_at >= :start AND created_at < :end_exclusive",
        p,
    )
    near_misses = _scalar(
        db,
        "SELECT COUNT(*) FROM near_misses WHERE organisation_id=:org "
        "AND created_at >= :start AND created_at < :end_exclusive",
        p,
    )
    walks = _scalar(
        db,
        "SELECT COUNT(*) FROM safety_walks WHERE organisation_id=:org "
        "AND created_at >= :start AND created_at < :end_exclusive",
        p,
    )

    # A healthy organisation reports many near misses per incident. A low ratio
    # means under-reporting, which is itself a risk signal.
    ratio = (near_misses / incidents) if incidents else (near_misses or 0)
    reporting_health = 100.0 if ratio < 1 else max(0.0, 100.0 - min(100.0, ratio * 10))
    org_health = round(
        0.5 * reporting_health
        + 0.3 * _pct(capa_overdue, max(capa_total, 1))
        + 0.2 * (100.0 if walks == 0 else max(0.0, 100.0 - min(100.0, walks * 10))),
        2,
    )
    inputs["org_health"] = {
        "incidents": incidents,
        "near_misses": near_misses,
        "near_miss_to_incident_ratio": round(ratio, 2),
        "safety_walks": walks,
    }

    return {
        "hazard_exposure": hazard_exposure,
        "control_integrity": control_integrity,
        "work_discipline": work_discipline,
        "human_readiness": human_readiness,
        "org_health": org_health,
        "inputs": inputs,
    }


def count_stale_sources(db: Session, org_id: Optional[int]) -> int:
    """Feeds not verified in the last 14 days — the Data Quality Gate.

    "Verify feeds current — any source >14 days stale = Data Gap, applying a
    10-point SPS penalty."
    """
    cutoff = datetime.now() - timedelta(days=SPS_STALE_DAYS)
    stale = 0
    for table in (
        "training_records",
        "fatigue_declarations",
        "competence_matrix",
        "contractor_companies",
        "vehicles",
    ):
        latest = _scalar(
            db,
            f"SELECT UNIX_TIMESTAMP(MAX(COALESCE(last_verified_at, updated_at))) "
            f"FROM {table} WHERE organisation_id=:org",
            {"org": org_id},
        )
        if latest == 0 or datetime.fromtimestamp(latest) < cutoff:
            stale += 1
    return stale


def compute_sps(
    db: Session,
    org_id: Optional[int],
    period_start: date,
    period_end: date,
    site_id: Optional[int] = None,
) -> tuple:
    """Returns (SpsResult, domain inputs) for one period."""
    domains = compute_domains(db, org_id, period_start, period_end, site_id)
    inputs = domains.pop("inputs")
    stale = count_stale_sources(db, org_id)

    result: SpsResult = safety_performance_score(
        hazard_exposure=domains["hazard_exposure"],
        control_integrity=domains["control_integrity"],
        work_discipline=domains["work_discipline"],
        human_readiness=domains["human_readiness"],
        org_health=domains["org_health"],
        stale_sources=stale,
        data_completeness=round(max(0.0, 100.0 - stale * 20), 2),
    )
    return result, {"domains": domains, "sources": inputs, "stale_sources": stale}
