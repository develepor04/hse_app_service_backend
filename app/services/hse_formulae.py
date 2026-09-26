"""The four deterministic formulae from HSE_Mobile_Architecture_v4.

"Fixed, human-defined, auditable. Every output traces to an explicit rule."

Transcribed verbatim from the algorithmic specification. These are pure
functions on purpose — no DB, no I/O — so the same code backs the API, the
gate engine, the weekly SPS batch and the unit tests, and so an auditor can
read the rule next to the number it produced.

Nothing in this module may be made probabilistic or AI-assisted. The AI layer
may add context around a verdict but never changes one.
"""
from dataclasses import dataclass, field
from typing import Optional


# ══════════════════════════════════════════════════════════════════════════════
# WF-06 · Fatigue Index — feeds C7 and gate 3
#
#   F = ((Shift Hrs - 8) x 1.5) + ((Consec. Days - 5) x 2) + (Night Shifts in 7d x 3)
#
#   <10   acceptable
#   10-14 amber, supervisor acknowledges
#   15-19 sign-off before high-risk permit
#   >=20  hard block, 8 h rest, Safety Manager exception only
#
# TODO(client): the formula below is from HSE_Mobile_Architecture_v4. The newer
# client spec — "EHSERA AI Orchestration Platform ISMS v1.0" (Aug 2026), WF-07 —
# states a DIFFERENT formula against the SAME 10/15/20 thresholds:
#
#   FI = (Hours worked in shift) + (Consecutive days x 2) + (Night shifts in 7d x 3)
#
# No subtraction, no floor. The two disagree materially: 12 h, 6 consecutive
# days, 2 night shifts scores 14 here (amber) and 30 under the new spec
# (mandatory stand-down). On the new formula an ordinary 10-hour day shift
# scores 10 and flags amber on its own, which suggests either its formula or its
# thresholds are mis-stated in the document.
#
# NOT changed pending a client answer, because gate 3 in
# app/services/gate_engine.py blocks permits on this number and switching would
# re-band every live worker. Note also that the workflow is WF-06 here and
# WF-07 in the new spec — the numbering shifted from WF-06 onward.
# ══════════════════════════════════════════════════════════════════════════════

FATIGUE_ACCEPTABLE = "acceptable"
FATIGUE_AMBER = "amber"
FATIGUE_SIGNOFF = "signoff"
FATIGUE_BLOCK = "block"


@dataclass
class FatigueResult:
    fatigue_index: float
    band: str
    shift_component: float
    consecutive_component: float
    night_component: float
    requires_supervisor_ack: bool
    requires_signoff: bool
    is_hard_block: bool
    explanation: str


def fatigue_index(
    shift_hours: float,
    consecutive_days: int,
    night_shifts_7d: int,
) -> FatigueResult:
    """Deterministic fatigue index from non-medical proxies only.

    Each term is floored at zero: an 6-hour shift is not "negative fatigue", it
    simply contributes nothing. Without the floor a short shift would mask
    genuine consecutive-day or night-shift load.
    """
    shift_component = max(0.0, (float(shift_hours) - 8.0) * 1.5)
    consecutive_component = max(0.0, (float(consecutive_days) - 5.0) * 2.0)
    night_component = max(0.0, float(night_shifts_7d) * 3.0)

    f = round(shift_component + consecutive_component + night_component, 2)

    if f >= 20:
        band = FATIGUE_BLOCK
        why = "Hard block — 8 h rest required. Safety Manager exception only."
    elif f >= 15:
        band = FATIGUE_SIGNOFF
        why = "Supervisor sign-off required before a high-risk permit."
    elif f >= 10:
        band = FATIGUE_AMBER
        why = "Amber — supervisor must acknowledge before work proceeds."
    else:
        band = FATIGUE_ACCEPTABLE
        why = "Within acceptable limits."

    return FatigueResult(
        fatigue_index=f,
        band=band,
        shift_component=round(shift_component, 2),
        consecutive_component=round(consecutive_component, 2),
        night_component=round(night_component, 2),
        requires_supervisor_ack=band in (FATIGUE_AMBER, FATIGUE_SIGNOFF),
        requires_signoff=band == FATIGUE_SIGNOFF,
        is_hard_block=band == FATIGUE_BLOCK,
        explanation=(
            f"F = (({shift_hours} - 8) x 1.5) + (({consecutive_days} - 5) x 2) "
            f"+ ({night_shifts_7d} x 3) = {f}. {why}"
        ),
    )


# ══════════════════════════════════════════════════════════════════════════════
# WF-07 · Safety Performance Score
#
#   SPS = 0.25 Hazard Exposure + 0.25 Control Integrity + 0.20 Work Discipline
#       + 0.20 Human Readiness + 0.10 Org. Health
#
#   Weekly batch. Measures the current state — it does not predict.
#   Bands: critical >=75 · high 50-74 · elevated 25-49 · acceptable 10-24 · low <10
# ══════════════════════════════════════════════════════════════════════════════

SPS_WEIGHTS = {
    "hazard_exposure": 0.25,
    "control_integrity": 0.25,
    "work_discipline": 0.20,
    "human_readiness": 0.20,
    "org_health": 0.10,
}

# Stale feeds (>14 days) are penalised 10 points — the Data Quality Gate.
SPS_STALE_DATA_PENALTY = 10.0
SPS_STALE_DAYS = 14


@dataclass
class SpsResult:
    sps: float
    band: str
    domains: dict
    weights: dict
    stale_data_penalty: float
    data_completeness: float
    explanation: str


def sps_band(score: float) -> str:
    if score >= 75:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 25:
        return "elevated"
    if score >= 10:
        return "acceptable"
    return "low"


def safety_performance_score(
    hazard_exposure: float,
    control_integrity: float,
    work_discipline: float,
    human_readiness: float,
    org_health: float,
    stale_sources: int = 0,
    data_completeness: float = 100.0,
) -> SpsResult:
    """Weighted five-domain score, 0-100, where higher means worse.

    `stale_sources` applies the spec's Data Quality Gate: any feed more than 14
    days old adds a 10-point penalty, because an incomplete picture must not
    read as a safe one.
    """
    domains = {
        "hazard_exposure": float(hazard_exposure),
        "control_integrity": float(control_integrity),
        "work_discipline": float(work_discipline),
        "human_readiness": float(human_readiness),
        "org_health": float(org_health),
    }

    weighted = sum(domains[k] * SPS_WEIGHTS[k] for k in SPS_WEIGHTS)
    penalty = SPS_STALE_DATA_PENALTY if stale_sources > 0 else 0.0
    score = round(min(100.0, max(0.0, weighted + penalty)), 2)

    return SpsResult(
        sps=score,
        band=sps_band(score),
        domains=domains,
        weights=dict(SPS_WEIGHTS),
        stale_data_penalty=penalty,
        data_completeness=round(float(data_completeness), 2),
        explanation=(
            "SPS = "
            + " + ".join(f"{SPS_WEIGHTS[k]}x{domains[k]:.1f}" for k in SPS_WEIGHTS)
            + (f" + {penalty} stale-data penalty" if penalty else "")
            + f" = {score} ({sps_band(score)})"
        ),
    )


# SPS alerts fire on delta >= 10 pts/week, a band change, or a KPI red-line.
SPS_ALERT_DELTA_THRESHOLD = 10.0


def sps_alerts_for(previous: Optional[SpsResult], current: SpsResult) -> list:
    """Which alerts this week's snapshot should raise against last week's."""
    alerts = []
    if previous is None:
        return alerts

    delta = round(current.sps - previous.sps, 2)
    if abs(delta) >= SPS_ALERT_DELTA_THRESHOLD:
        alerts.append(
            {
                "alert_type": "delta",
                "delta": delta,
                "severity": "high" if delta > 0 else "info",
                "message": (
                    f"Safety Performance Score moved {delta:+.1f} points in one week "
                    f"({previous.sps} to {current.sps})."
                ),
            }
        )

    if previous.band != current.band:
        alerts.append(
            {
                "alert_type": "band_change",
                "delta": delta,
                "previous_band": previous.band,
                "new_band": current.band,
                "severity": "high" if current.sps > previous.sps else "info",
                "message": f"SPS band changed from {previous.band} to {current.band}.",
            }
        )

    return alerts


# ══════════════════════════════════════════════════════════════════════════════
# WF-09 · Journey Risk Score
#
#   JRS = Route(1-3) x Mode(1-4) x Cargo(1-3)
#
#   1-4 low · 5-12 medium · >=13 high, requires Transport Authorisation
#   Check-in: road every 2 h · marine per voyage plan · air per flight plan
# ══════════════════════════════════════════════════════════════════════════════

JOURNEY_CHECKIN_MINUTES = {
    "road": 120,      # every 2 h
    "rail": 180,
    "marine": 240,    # per voyage plan
    "air": 240,       # per flight plan
}


@dataclass
class JourneyRiskResult:
    journey_risk_score: int
    risk_band: str
    requires_authorisation: bool
    checkin_interval_minutes: int
    explanation: str


def journey_risk_score(
    route_score: int,
    mode_score: int,
    cargo_score: int,
    transport_mode: str = "road",
) -> JourneyRiskResult:
    route = max(1, min(3, int(route_score)))
    mode = max(1, min(4, int(mode_score)))
    cargo = max(1, min(3, int(cargo_score)))

    jrs = route * mode * cargo

    if jrs >= 13:
        band = "high"
    elif jrs >= 5:
        band = "medium"
    else:
        band = "low"

    return JourneyRiskResult(
        journey_risk_score=jrs,
        risk_band=band,
        # ">=13 high, requires Transport Authorisation"
        requires_authorisation=jrs >= 13,
        checkin_interval_minutes=JOURNEY_CHECKIN_MINUTES.get(
            (transport_mode or "road").lower(), 120
        ),
        explanation=(
            f"JRS = Route({route}) x Mode({mode}) x Cargo({cargo}) = {jrs} ({band})."
            + (" Transport Authorisation required." if jrs >= 13 else "")
        ),
    )


# ══════════════════════════════════════════════════════════════════════════════
# WF-08 · Contractor gates
#
#   RAMS = sum of 6 criteria x 0-20
#          <60 reject · 60-79 conditional · >=80 approve
#   LTIFR vs IOGP benchmark
#          >2x = rejected · 1.5-2x conditional with enhanced monitoring
#
# TODO(client): which scale do the 60/80 thresholds sit on? The client's own two
# documents contradict each other, and so does our code:
#   · "EHSERA AI Orchestration Platform ISMS v1.0" WF-09 heads the rubric
#     "6 Criteria, 0-20 pts each, Max 100" — but 6 x 20 = 120, so the heading is
#     arithmetically wrong, and its thresholds read as percentages.
#   · "EHSERA AI Platform Enterprise Architecture ISMS v1.0" CAP-RAMS-001 says
#     "0-20 points each, max 120" and puts human review at <60.
#   · rams_score below bands on the RAW 0-120 sum, while
#     app/controllers/contractor.py:359 normalises avg_rams/120*100 for the
#     contractor scorecard. Both scales are live.
#
# NOT changed pending a client answer — re-scaling silently re-bands every
# historical verdict in rams_scores.verdict. Gate 5 of the Integration Spine
# reads the same number ("RAMS scored >= 60"), which only makes sense on the raw
# scale, which is why the raw reading was chosen originally.
# ══════════════════════════════════════════════════════════════════════════════

RAMS_CRITERIA = (
    "hazard_identification",
    "control_adequacy",
    "competence_evidence",
    "equipment_suitability",
    "emergency_arrangements",
    "supervision_arrangements",
)


@dataclass
class RamsResult:
    total_score: int
    verdict: str  # reject | conditional | approve
    criteria: dict = field(default_factory=dict)
    explanation: str = ""


def rams_score(**criteria) -> RamsResult:
    """Six criteria, 0-20 each, summed to a raw 0-120 score.

    The spec states the bands (<60 reject, 60-79 conditional, >=80 approve)
    directly against this sum, and gate 5 reads the same number ("RAMS scored
    >= 60"), so the bands are applied to the raw total rather than to a
    percentage. Do not normalise — it would shift every verdict by a band.
    """
    values = {}
    for key in RAMS_CRITERIA:
        values[key] = max(0, min(20, int(criteria.get(key, 0) or 0)))

    raw = sum(values.values())  # 0-120

    if raw >= 80:
        verdict = "approve"
    elif raw >= 60:
        verdict = "conditional"
    else:
        verdict = "reject"

    return RamsResult(
        total_score=raw,
        verdict=verdict,
        criteria=values,
        explanation=(
            f"RAMS = {' + '.join(str(v) for v in values.values())} = {raw}/120 -> {verdict}."
        ),
    )


@dataclass
class LtifrResult:
    ratio: Optional[float]
    verdict: str  # approve | conditional | reject | unknown
    explanation: str


def ltifr_vs_benchmark(
    contractor_ltifr: Optional[float],
    benchmark_ltifr: Optional[float],
) -> LtifrResult:
    """>2x benchmark = rejected. 1.5-2x = conditional with enhanced monitoring."""
    if contractor_ltifr is None or not benchmark_ltifr:
        return LtifrResult(
            ratio=None,
            verdict="unknown",
            explanation="No LTIFR or no IOGP benchmark on file — not tracked.",
        )

    ratio = round(float(contractor_ltifr) / float(benchmark_ltifr), 3)

    if ratio > 2.0:
        verdict = "reject"
        why = "More than 2x the IOGP benchmark."
    elif ratio >= 1.5:
        verdict = "conditional"
        why = "1.5-2x benchmark — conditional, with enhanced monitoring."
    else:
        verdict = "approve"
        why = "At or below benchmark expectations."

    return LtifrResult(
        ratio=ratio,
        verdict=verdict,
        explanation=f"LTIFR {contractor_ltifr} vs IOGP {benchmark_ltifr} = {ratio}x. {why}",
    )


def contractor_scorecard_verdict(score: float, prior_quarter_score: Optional[float] = None) -> str:
    """<50 enhanced oversight · <30 contract review · two quarters <30 = off list."""
    if score < 30 and prior_quarter_score is not None and prior_quarter_score < 30:
        return "off_list"
    if score < 30:
        return "contract_review"
    if score < 50:
        return "enhanced_oversight"
    return "ok"
