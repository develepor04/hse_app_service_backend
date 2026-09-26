"""THE INTEGRATION SPINE · deterministic gate engine.

Server-side at permit issuance and journey departure. Rule-based and auditable.
The AI layer may add context but never changes a verdict.

    1 · RAMS Linked            Task has a current, approved risk assessment
    2 · Competence Verified    Every named worker holds valid certs for the
                               permit type. Expired safety-critical cert = hard block.
    3 · Fatigue Index          <10 pass · 10-14 ack · 15-19 sign-off · >=20 hard block
    4 · Zone / SIMOPS          No two high-energy permits active within 30 m
    5 · Contractor Approved    Company pre-qualified and RAMS scored >= 60
    6 · Weather & Journey      Mode operating limits not exceeded, score >=13
                               requires Transport Authorisation

Every evaluation is written to gate_decision_log. A blocked gate can only be
passed by an explicit, reasoned override (override_log) by a role entitled to
give one — and gate 2's expired-safety-critical-certificate case and gate 3's
>=20 fatigue case are hard blocks the AI can never lift.
"""
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.competence import CompetenceMatrix, TrainingRecord
from app.models.contractor import ContractorCompany, RamsScore
from app.models.fatigue import FatigueDeclaration
from app.models.gates import GateDecisionLog
from app.models.permit_to_work import PermitToWork
from app.models.transport import WeatherLimitTable
from app.services.hse_formulae import fatigue_index, journey_risk_score
from app.services.workflow_stages import PERMIT_LIVE_STATUSES

PASS = "pass"
AMBER = "amber"
BLOCK = "block"

GATE_RAMS = "rams_linked"
GATE_COMPETENCE = "competence_verified"
GATE_FATIGUE = "fatigue_index"
GATE_ZONE = "zone_simops"
GATE_CONTRACTOR = "contractor_approved"
GATE_WEATHER = "weather_journey"

# "No two high-energy permits active within 30 m"
SIMOPS_RADIUS_M = 30.0


@dataclass
class GateResult:
    gate_key: str
    verdict: str
    reason: str
    details: dict
    # A hard block is one no override may lift — an expired safety-critical
    # certificate, or a fatigue index at or above 20.
    hard: bool = False

    @property
    def passed(self) -> bool:
        return self.verdict == PASS


@dataclass
class GateEvaluation:
    overall: str
    gates: List[GateResult]
    blocked_reasons: List[str]

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "blocked_reasons": self.blocked_reasons,
            "gates": [asdict(g) for g in self.gates],
        }


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = radians(float(lat1)), radians(float(lat2))
    dp = radians(float(lat2) - float(lat1))
    dl = radians(float(lon2) - float(lon1))
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * r * asin(sqrt(a))


# ── Gate 1 · RAMS linked ──────────────────────────────────────────────────────
def gate_rams_linked(db: Session, org_id: Optional[int], permit: PermitToWork) -> GateResult:
    """The task must carry a current, approved risk assessment (WF-01).

    Two things can satisfy this, and they are not the same artefact.

    A **Flow B risk assessment** is what the spec means: ten categories, a
    residual score, a signature. It is checked first, and an approved one that
    has not passed its review date passes the gate outright.

    A **RAMS score** is the older path — a contractor's method statement scored
    out of 120 by the six-criteria scorer. Every permit in this database
    predates Flow B and is linked this way, so removing it would block every
    existing permit overnight. It stays as a fallback.

    With neither, the permit is blocked and the assessment's absence also feeds
    the +2 `no_valid_rams` uplift on the risk side — the spec applies both, and
    they are doing different jobs: the uplift makes the score honest, the block
    stops the work.
    """
    from app.services import risk_assessment as ra_svc

    assessment = None
    if getattr(permit, "risk_assessment_id", None):
        from app.models.risk_assessment import RiskAssessment
        assessment = (
            db.query(RiskAssessment)
            .filter(
                RiskAssessment.id == permit.risk_assessment_id,
                RiskAssessment.organisation_id == org_id,
            )
            .first()
        )
    if assessment is None:
        # Nothing linked by hand, so look for one covering where the work is.
        assessment = ra_svc.covering_assessment(
            db, org_id,
            station_id=permit.location_station_id,
            site_id=getattr(permit, "site_id", None),
        )

    if assessment is not None:
        detail = {"risk_assessment_id": assessment.id, "residual_score": assessment.residual_score}
        if assessment.status != "approved" or assessment.approved_at is None:
            return GateResult(
                GATE_RAMS, BLOCK,
                f"RA-{assessment.id} covers this work but is not approved "
                f"(currently {assessment.status}).",
                detail,
            )
        if ra_svc.is_expired(assessment):
            return GateResult(
                GATE_RAMS, BLOCK,
                f"RA-{assessment.id} passed its review date on "
                f"{assessment.review_due_at:%d %b %Y} and is no longer current.",
                detail,
            )
        if assessment.flagged_for_review:
            # Still valid, but something in the field has contradicted it.
            return GateResult(
                GATE_RAMS, AMBER,
                f"RA-{assessment.id} is approved but flagged for review: "
                f"{assessment.flagged_reason}",
                detail,
            )
        return GateResult(
            GATE_RAMS, PASS,
            f"RA-{assessment.id} approved, residual {assessment.residual_score} "
            f"{assessment.residual_band}.",
            detail,
        )

    rams = (
        db.query(RamsScore)
        .filter(RamsScore.permit_id == permit.id)
        .order_by(RamsScore.id.desc())
        .first()
    )
    if rams is None:
        return GateResult(
            GATE_RAMS, BLOCK,
            "No approved risk assessment covers this work. No assessment, no permit.",
            {"rams_score_id": None, "risk_assessment_id": None},
        )
    if rams.verdict == "reject":
        return GateResult(
            GATE_RAMS, BLOCK,
            f"Linked RAMS scored {rams.total_score}/120 and was rejected.",
            {"rams_score_id": rams.id, "total_score": rams.total_score},
        )
    if rams.verdict == "conditional":
        return GateResult(
            GATE_RAMS, AMBER,
            f"Linked RAMS scored {rams.total_score}/120 — conditional approval.",
            {"rams_score_id": rams.id, "total_score": rams.total_score},
        )
    return GateResult(
        GATE_RAMS, PASS,
        f"RAMS {rams.total_score}/120 approved.",
        {"rams_score_id": rams.id, "total_score": rams.total_score},
    )


# ── Gate 2 · Competence verified ──────────────────────────────────────────────
def gate_competence_verified(
    db: Session,
    org_id: Optional[int],
    employee_ids: List[int],
    permit_type_id: Optional[int] = None,
    on_date: Optional[date] = None,
) -> GateResult:
    """Every named worker must hold valid certs for the permit type.

    An expired safety-critical certificate is a hard block — the spec is
    explicit that this is one the AI may advise on but can never lift.
    """
    today = on_date or date.today()
    if not employee_ids:
        return GateResult(
            GATE_COMPETENCE, AMBER,
            "No workers named on this permit — competence could not be checked.",
            {"employee_ids": []},
        )

    requirements = (
        db.query(CompetenceMatrix)
        .filter(CompetenceMatrix.organisation_id == org_id)
        .filter(CompetenceMatrix.is_mandatory == 1)
        .all()
    )
    # A requirement with no permit_types_gated gates every permit type.
    applicable = [
        r for r in requirements
        if not r.permit_types_gated
        or permit_type_id is None
        or permit_type_id in (r.permit_types_gated or [])
    ]

    if not applicable:
        return GateResult(
            GATE_COMPETENCE, AMBER,
            "No competence matrix is configured for this organisation — "
            "the permit gate has nothing to check against.",
            {"requirements": 0},
        )

    failures, expiring, hard = [], [], False
    for emp_id in employee_ids:
        records = (
            db.query(TrainingRecord)
            .filter(TrainingRecord.employee_id == emp_id)
            .filter(TrainingRecord.result == "pass")
            .all()
        )
        for req in applicable:
            match = next(
                (
                    r for r in records
                    if (req.certification_type_id and r.certification_type_id == req.certification_type_id)
                    or (req.training_program_id and r.training_program_id == req.training_program_id)
                    or (r.competence_matrix_id == req.id)
                ),
                None,
            )
            if match is None:
                failures.append(
                    {"employee_id": emp_id, "requirement": req.requirement_name, "state": "missing",
                     "safety_critical": bool(req.is_safety_critical)}
                )
                if req.is_safety_critical:
                    hard = True
            elif match.expires_at and match.expires_at < today:
                failures.append(
                    {"employee_id": emp_id, "requirement": req.requirement_name, "state": "expired",
                     "expired_on": str(match.expires_at), "safety_critical": bool(req.is_safety_critical)}
                )
                if req.is_safety_critical:
                    hard = True
            elif match.expires_at and match.expires_at <= today + timedelta(days=30):
                expiring.append(
                    {"employee_id": emp_id, "requirement": req.requirement_name,
                     "expires_on": str(match.expires_at)}
                )

    if failures:
        critical = [f for f in failures if f["safety_critical"]]
        return GateResult(
            GATE_COMPETENCE, BLOCK,
            (
                f"{len(critical)} expired or missing safety-critical certificate(s)."
                if critical
                else f"{len(failures)} competence requirement(s) not met."
            ),
            {"failures": failures, "expiring": expiring},
            hard=hard,
        )
    if expiring:
        return GateResult(
            GATE_COMPETENCE, AMBER,
            f"{len(expiring)} certificate(s) expire within 30 days.",
            {"expiring": expiring},
        )
    return GateResult(
        GATE_COMPETENCE, PASS,
        f"All {len(applicable)} requirement(s) met for {len(employee_ids)} worker(s).",
        {"requirements": len(applicable), "workers": len(employee_ids)},
    )


# ── Gate 3 · Fatigue index ────────────────────────────────────────────────────
def gate_fatigue(
    db: Session,
    org_id: Optional[int],
    employee_ids: List[int],
    is_high_risk: bool = False,
) -> GateResult:
    """Latest declaration per worker, banded by the WF-06 formula.

    >=20 is a hard block requiring 8 h rest — Safety Manager exception only.
    """
    if not employee_ids:
        return GateResult(GATE_FATIGUE, AMBER, "No workers named — fatigue not checked.", {})

    worst, details = None, []
    for emp_id in employee_ids:
        decl = (
            db.query(FatigueDeclaration)
            .filter(FatigueDeclaration.employee_id == emp_id)
            .order_by(FatigueDeclaration.id.desc())
            .first()
        )
        if decl is None:
            details.append({"employee_id": emp_id, "state": "not_declared"})
            continue

        r = fatigue_index(
            float(decl.shift_hours or 0),
            int(decl.consecutive_days or 0),
            int(decl.night_shifts_7d or 0),
        )
        entry = {
            "employee_id": emp_id,
            "fatigue_index": r.fatigue_index,
            "band": r.band,
            "declared_at": str(decl.declared_at) if decl.declared_at else None,
            "supervisor_acknowledged": decl.supervisor_ack_at is not None,
            "supervisor_signed_off": decl.supervisor_signoff_at is not None,
            "safety_manager_exception": decl.exception_at is not None,
        }
        details.append(entry)
        if worst is None or r.fatigue_index > worst[0].fatigue_index:
            worst = (r, decl, emp_id)

    missing = [d for d in details if d.get("state") == "not_declared"]
    if missing and not worst:
        return GateResult(
            GATE_FATIGUE, AMBER,
            f"{len(missing)} worker(s) have not declared fatigue for this shift.",
            {"workers": details},
        )

    r, decl, emp_id = worst
    if r.is_hard_block:
        # Only a Safety Manager exception with a written reason can pass this.
        if decl.exception_at and decl.exception_reason:
            return GateResult(
                GATE_FATIGUE, AMBER,
                f"Fatigue index {r.fatigue_index} — Safety Manager exception on file.",
                {"workers": details, "exception_reason": decl.exception_reason},
            )
        return GateResult(
            GATE_FATIGUE, BLOCK,
            f"Fatigue index {r.fatigue_index} (>=20). Hard block — 8 h rest required. "
            "Safety Manager exception only.",
            {"workers": details},
            hard=True,
        )

    if r.requires_signoff and is_high_risk and not decl.supervisor_signoff_at:
        return GateResult(
            GATE_FATIGUE, BLOCK,
            f"Fatigue index {r.fatigue_index} (15-19) requires supervisor sign-off "
            "before a high-risk permit.",
            {"workers": details},
        )
    if r.requires_supervisor_ack and not decl.supervisor_ack_at:
        return GateResult(
            GATE_FATIGUE, AMBER,
            f"Fatigue index {r.fatigue_index} — supervisor acknowledgement required.",
            {"workers": details},
        )

    return GateResult(
        GATE_FATIGUE, PASS,
        f"Highest fatigue index {r.fatigue_index} ({r.band}).",
        {"workers": details},
    )


# ── Gate 4 · Zone / SIMOPS ────────────────────────────────────────────────────
def gate_zone_simops(db: Session, org_id: Optional[int], permit: PermitToWork) -> GateResult:
    """No two high-energy permits active within 30 m.

    Proximity is measured by GPS when both permits carry it, and falls back to
    an exact zone match when they do not.
    """
    if not permit.is_high_energy:
        return GateResult(GATE_ZONE, PASS, "Not a high-energy permit — SIMOPS not applicable.", {})

    others = (
        db.query(PermitToWork)
        .filter(PermitToWork.organisation_id == org_id)
        .filter(PermitToWork.id != permit.id)
        .filter(PermitToWork.is_high_energy == 1)
        # Anything that authorises work right now, plus `acknowledged` — a permit
        # already through supervisor review is close enough to issue that a
        # SIMOPS clash is worth flagging before it is granted. This filtered on
        # `approved`, which nothing writes, so issued permits never clashed.
        .filter(PermitToWork.workflow_status.in_(list(PERMIT_LIVE_STATUSES) + ["acknowledged"]))
        .all()
    )

    clashes = []
    for o in others:
        if permit.gps_latitude and permit.gps_longitude and o.gps_latitude and o.gps_longitude:
            d = _haversine_m(permit.gps_latitude, permit.gps_longitude,
                             o.gps_latitude, o.gps_longitude)
            if d <= SIMOPS_RADIUS_M:
                clashes.append({"permit_id": o.id, "distance_m": round(d, 1), "basis": "gps"})
        elif permit.zone and o.zone and permit.zone == o.zone:
            clashes.append({"permit_id": o.id, "zone": o.zone, "basis": "zone"})

    if clashes:
        return GateResult(
            GATE_ZONE, BLOCK,
            f"{len(clashes)} other high-energy permit(s) active within {SIMOPS_RADIUS_M:.0f} m.",
            {"clashes": clashes},
        )
    return GateResult(GATE_ZONE, PASS, "No conflicting high-energy permits nearby.", {})


# ── Gate 5 · Contractor approved ──────────────────────────────────────────────
def gate_contractor_approved(db: Session, org_id: Optional[int], permit: PermitToWork) -> GateResult:
    """Company pre-qualified and RAMS scored >= 60."""
    if not permit.contractor_company_id:
        return GateResult(GATE_CONTRACTOR, PASS, "No contractor on this permit — own workforce.", {})

    co = (
        db.query(ContractorCompany)
        .filter(ContractorCompany.id == permit.contractor_company_id)
        .first()
    )
    if co is None:
        return GateResult(GATE_CONTRACTOR, BLOCK, "Contractor company not found in the registry.", {})

    if co.suspended:
        return GateResult(
            GATE_CONTRACTOR, BLOCK,
            f"{co.company_name} is suspended: {co.suspended_reason or 'no reason recorded'}.",
            {"contractor_company_id": co.id},
        )
    if co.prequalification_status == "barred":
        return GateResult(
            GATE_CONTRACTOR, BLOCK, f"{co.company_name} is barred.",
            {"contractor_company_id": co.id},
        )
    if co.prequalification_status == "pending":
        return GateResult(
            GATE_CONTRACTOR, BLOCK, f"{co.company_name} is not pre-qualified.",
            {"contractor_company_id": co.id},
        )
    if co.insurance_expiry and co.insurance_expiry < date.today():
        return GateResult(
            GATE_CONTRACTOR, BLOCK,
            f"{co.company_name} insurance expired on {co.insurance_expiry}.",
            {"contractor_company_id": co.id},
        )

    rams = (
        db.query(RamsScore)
        .filter(RamsScore.permit_id == permit.id)
        .order_by(RamsScore.id.desc())
        .first()
    )
    if rams and rams.total_score < 60:
        return GateResult(
            GATE_CONTRACTOR, BLOCK,
            f"Contractor RAMS scored {rams.total_score}/120 — below the 60 threshold.",
            {"contractor_company_id": co.id, "total_score": rams.total_score},
        )

    if co.prequalification_status == "conditional":
        return GateResult(
            GATE_CONTRACTOR, AMBER,
            f"{co.company_name} is conditionally approved — enhanced monitoring applies.",
            {"contractor_company_id": co.id},
        )
    return GateResult(
        GATE_CONTRACTOR, PASS, f"{co.company_name} is pre-qualified.",
        {"contractor_company_id": co.id},
    )


# ── Gate 6 · Weather & journey ────────────────────────────────────────────────
def gate_weather_journey(
    db: Session,
    org_id: Optional[int],
    transport_mode: str = "road",
    route_score: int = 1,
    mode_score: int = 1,
    cargo_score: int = 1,
    weather: Optional[dict] = None,
    authorised: bool = False,
) -> GateResult:
    """Mode operating limits not exceeded. Score >=13 requires authorisation."""
    jrs = journey_risk_score(route_score, mode_score, cargo_score, transport_mode)
    details = {
        "journey_risk_score": jrs.journey_risk_score,
        "risk_band": jrs.risk_band,
        "checkin_interval_minutes": jrs.checkin_interval_minutes,
    }

    limits = (
        db.query(WeatherLimitTable)
        .filter(WeatherLimitTable.organisation_id == org_id)
        .filter(WeatherLimitTable.transport_mode == (transport_mode or "road").lower())
        .first()
    )

    breaches = []
    if limits and weather:
        if limits.max_wind_kph and weather.get("wind_kph") is not None:
            if float(weather["wind_kph"]) > float(limits.max_wind_kph):
                breaches.append(f"wind {weather['wind_kph']} kph > limit {limits.max_wind_kph}")
        if limits.min_visibility_m and weather.get("visibility_m") is not None:
            if float(weather["visibility_m"]) < float(limits.min_visibility_m):
                breaches.append(
                    f"visibility {weather['visibility_m']} m < minimum {limits.min_visibility_m}"
                )
        if limits.max_precip_mm_hr and weather.get("precip_mm_hr") is not None:
            if float(weather["precip_mm_hr"]) > float(limits.max_precip_mm_hr):
                breaches.append(
                    f"precipitation {weather['precip_mm_hr']} mm/h > limit {limits.max_precip_mm_hr}"
                )
        if limits.max_wave_height_m and weather.get("wave_height_m") is not None:
            if float(weather["wave_height_m"]) > float(limits.max_wave_height_m):
                breaches.append(
                    f"wave height {weather['wave_height_m']} m > limit {limits.max_wave_height_m}"
                )

    details["weather_breaches"] = breaches
    if breaches:
        return GateResult(
            GATE_WEATHER, BLOCK,
            f"{transport_mode} operating limits exceeded: " + "; ".join(breaches) + ".",
            details,
        )

    if jrs.requires_authorisation and not authorised:
        return GateResult(
            GATE_WEATHER, BLOCK,
            f"Journey risk {jrs.journey_risk_score} (high) requires Transport Authorisation.",
            details,
        )

    return GateResult(GATE_WEATHER, PASS, jrs.explanation, details)


# ── Orchestration ─────────────────────────────────────────────────────────────
def _log(
    db: Session,
    org_id: Optional[int],
    subject_type: str,
    subject_id: Optional[int],
    results: List[GateResult],
    evaluated_by: Optional[int] = None,
    subject_employee_id: Optional[int] = None,
) -> None:
    now = datetime.now()
    for r in results:
        db.add(
            GateDecisionLog(
                organisation_id=org_id,
                subject_type=subject_type,
                subject_id=subject_id,
                gate_key=r.gate_key,
                verdict=r.verdict,
                reason=r.reason,
                details={**r.details, "hard": r.hard},
                subject_employee_id=subject_employee_id,
                evaluated_by=evaluated_by,
                evaluated_at=now,
                source_system="server",
                last_verified_at=now,
            )
        )
    db.commit()


def _combine(results: List[GateResult]) -> GateEvaluation:
    blocked = [r for r in results if r.verdict == BLOCK]
    amber = [r for r in results if r.verdict == AMBER]
    overall = BLOCK if blocked else (AMBER if amber else PASS)
    return GateEvaluation(
        overall=overall,
        gates=results,
        blocked_reasons=[f"{r.gate_key}: {r.reason}" for r in blocked],
    )


def evaluate_permit_gates(
    db: Session,
    org_id: Optional[int],
    permit: PermitToWork,
    employee_ids: Optional[List[int]] = None,
    evaluated_by: Optional[int] = None,
    persist: bool = True,
) -> GateEvaluation:
    """Run all six gates for a permit. This is what stands between a request
    and an issued permit."""
    employee_ids = employee_ids or [e for e in [permit.requested_by] if e]
    is_high_risk = bool(permit.is_high_energy)

    results = [
        gate_rams_linked(db, org_id, permit),
        gate_competence_verified(db, org_id, employee_ids, permit.permit_type_id),
        gate_fatigue(db, org_id, employee_ids, is_high_risk=is_high_risk),
        gate_zone_simops(db, org_id, permit),
        gate_contractor_approved(db, org_id, permit),
    ]

    evaluation = _combine(results)
    if persist:
        _log(db, org_id, "permit", permit.id, results, evaluated_by,
             subject_employee_id=employee_ids[0] if employee_ids else None)
    return evaluation


def evaluate_journey_gates(
    db: Session,
    org_id: Optional[int],
    journey,
    employee_ids: Optional[List[int]] = None,
    weather: Optional[dict] = None,
    evaluated_by: Optional[int] = None,
    persist: bool = True,
) -> GateEvaluation:
    """Gates that apply at journey departure: competence, fatigue, weather."""
    employee_ids = employee_ids or [journey.employee_id]

    results = [
        gate_competence_verified(db, org_id, employee_ids),
        gate_fatigue(db, org_id, employee_ids, is_high_risk=journey.risk_band == "high"),
        gate_weather_journey(
            db, org_id,
            transport_mode=journey.transport_mode,
            route_score=journey.route_score,
            mode_score=journey.mode_score,
            cargo_score=journey.cargo_score,
            weather=weather or (journey.weather_snapshot or {}),
            authorised=journey.authorised_at is not None,
        ),
    ]

    evaluation = _combine(results)
    if persist:
        _log(db, org_id, "journey", journey.id, results, evaluated_by,
             subject_employee_id=employee_ids[0] if employee_ids else None)
    return evaluation
