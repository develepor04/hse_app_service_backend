"""Stage 02 ASSESS for every event family.

Source: HSE_Workflow_Engine_Slide.pptx — the same eight stages for hazards, near
misses, incidents, permits and audits.

Only incidents were ever assessed. A near miss, an unsafe act or a raised risk
went straight from RECORD to a supervisor's inbox with no triage at all, so the
one stage that decides how urgently anything gets handled was skipped for four
of the five families.

Each family answers the same three questions with its own rules:

    how bad is it   ·  how fast must we act  ·  does anyone outside need to know

The answers land on the shared assessment columns so a dashboard can rank a near
miss against an incident without special-casing either.

Every assessor is deterministic — L2 Rules Engine per the LEAN hierarchy. None
of them invokes a model.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.incident_severity import PRIORITY_LABELS, classify_severity
from app.services.risk_scoring import score_risk


@dataclass
class Assessment:
    """What stage 02 produces, whatever the event family."""
    priority: Optional[str] = None            # P1..P5 — one scale across families
    label: Optional[str] = None
    is_hipo: bool = False                     # could this have been much worse
    is_recurring: bool = False
    requires_systemic_rca: bool = False
    response_due_at: Optional[datetime] = None
    min_investigator: Optional[str] = None
    trace: List[str] = field(default_factory=list)
    explanation: str = ""
    # Family-specific extras (risk band, uplift detail, …) for the response only.
    extra: Dict[str, Any] = field(default_factory=dict)


# ── Shared: has this happened here before? ───────────────────────────────────

def _is_recurring(db: Session, table: str, record, type_column: str) -> bool:
    """Same event type at the same station within 12 months (WF-03 Q5).

    Scoped to the station rather than the organisation because "at this site" is
    what the rule asks — org-wide would flag almost everything.
    """
    type_value = getattr(record, type_column, None)
    station = getattr(record, "location_station_id", None)
    if not type_value or not station:
        return False

    # Each table names its own "when it happened" column: incidents use
    # incident_date_time, unsafe acts observed_date_time, near misses
    # event_date_time, the hazard register logged_at.
    reference = (
        getattr(record, "incident_date_time", None)
        or getattr(record, "observed_date_time", None)
        or getattr(record, "event_date_time", None)
        or getattr(record, "logged_at", None)
        or getattr(record, "reported_at", None)
        or datetime.utcnow()
    )
    count = db.execute(
        text(
            f"SELECT COUNT(*) FROM {table} "
            " WHERE organisation_id = :org AND location_station_id = :sid "
            f"  AND {type_column} = :tval AND id <> :self_id "
            "   AND created_at >= :since"
        ),
        {
            "org": record.organisation_id, "sid": station, "tval": type_value,
            "self_id": record.id or 0, "since": reference - timedelta(days=365),
        },
    ).scalar()
    return bool(count and count > 0)


# ══════════════════════════════════════════════════════════════════════════════
# Near miss
#
# A near miss has no injury by definition, so the WF-03 tree would file every
# one as P5. That is exactly the failure the spec's Q4 exists to prevent: a near
# miss whose worst-case outcome was a fatality is a high-potential incident and
# gets the P2 investigation protocol. Potential, not outcome, drives the
# priority here.
# ══════════════════════════════════════════════════════════════════════════════

# What the reporter says could have happened, mapped to the priority the event
# would have carried had it happened.
_POTENTIAL_PRIORITY = {
    "fatality": "P2",          # HIPO — P2 protocol per WF-03 Q4
    "major": "P2",
    "serious": "P3",
    "moderate": "P4",
    "minor": "P5",
    "negligible": "P5",
}

_SLA_DAYS = {"P1": 30, "P2": 15, "P3": 30, "P4": 5, "P5": 5}
_MIN_INVESTIGATOR = {
    "P1": "Safety Director", "P2": "Safety Manager", "P3": "Safety Advisor",
    "P4": "Safety Team", "P5": "Supervisor",
}


def assess_near_miss(db: Session, record) -> Assessment:
    potential = str(getattr(record, "potential_consequence", "") or "").strip().lower()
    worst_case_fatal = potential in ("fatality", "major")
    priority = _POTENTIAL_PRIORITY.get(potential, "P5")
    # near_misses carries no event-type column; the linked hazard is the closest
    # proxy for "this same thing nearly happened here before".
    recurring = _is_recurring(db, "near_misses", record, "hazard_id")

    trace = [f"Potential consequence = {potential or 'not stated'} -> {priority}"]
    if worst_case_fatal:
        trace.append("Worst case fatal/major -> HIPO, P2 investigation protocol")
    if recurring:
        trace.append("Same event type at this site within 12 months -> systemic RCA required")

    return _finish(
        priority, worst_case_fatal, recurring, record, trace,
        extra={"potential_consequence": potential or None},
    )


# ══════════════════════════════════════════════════════════════════════════════
# Unsafe act
#
# A one-off unsafe act is a coaching conversation. The same person doing the
# same thing repeatedly is a systemic problem — supervision, training or a
# control that makes the unsafe route the easy one. Repetition is what escalates
# it, so that is what this assessor looks for.
# ══════════════════════════════════════════════════════════════════════════════

def _repeat_by_same_person(db: Session, record) -> int:
    person = getattr(record, "person_observed", None)
    if not person:
        return 0
    return db.execute(
        text(
            "SELECT COUNT(*) FROM unsafe_acts "
            " WHERE organisation_id = :org AND person_observed = :p "
            "   AND id <> :self_id AND created_at >= :since"
        ),
        {
            "org": record.organisation_id, "p": person, "self_id": record.id or 0,
            "since": datetime.utcnow() - timedelta(days=365),
        },
    ).scalar() or 0


def assess_unsafe_act(db: Session, record) -> Assessment:
    repeats = _repeat_by_same_person(db, record)
    rule_violated = bool(getattr(record, "rule_violated", None))

    # A life-saving-rule breach is serious on its own. Otherwise repetition
    # drives it: third occurrence within a year is a pattern, not an accident.
    if rule_violated and repeats >= 1:
        priority = "P3"
    elif rule_violated or repeats >= 2:
        priority = "P4"
    else:
        priority = "P5"

    trace = [f"Rule violated = {rule_violated}", f"Prior acts by same person (12 mo) = {repeats}"]
    recurring = repeats >= 2
    if recurring:
        trace.append("Repeated unsafe act by the same individual -> systemic review required")

    return _finish(
        priority, False, recurring, record, trace,
        extra={"prior_acts_12m": repeats, "rule_violated": rule_violated},
    )


# ══════════════════════════════════════════════════════════════════════════════
# Risk / hazard report
#
# Already has a real scoring engine — WF-01 L x S with the four mandatory
# uplifts. Stage 02 reuses it rather than inventing a second scale, then maps
# the risk band onto the shared priority so a critical risk sorts alongside a
# P1 incident in the same queue.
# ══════════════════════════════════════════════════════════════════════════════

_BAND_PRIORITY = {"Critical": "P2", "High": "P3", "Medium": "P4", "Low": "P5"}


def assess_risk(db: Session, record) -> Assessment:
    result = score_risk(
        likelihood=getattr(record, "likelihood", None),
        severity=getattr(record, "consequence", None),
        raw_score=getattr(record, "raw_risk_score", None) or getattr(record, "risk_score", None),
        no_valid_rams=bool(getattr(record, "uplift_no_valid_rams", 0)),
        new_worker=bool(getattr(record, "uplift_new_worker", 0)),
        night_shift=bool(getattr(record, "uplift_night_shift", 0)),
        temporary_control=bool(getattr(record, "uplift_temporary_control", 0)),
    )
    priority = _BAND_PRIORITY.get(result.band or "", "P5")
    recurring = _is_recurring(db, "risk_reports", record, "risk_category")

    trace = [result.explanation]
    if recurring:
        trace.append("Same risk category at this site within 12 months -> systemic review")

    # HIPO means "could realistically have killed or seriously injured", which
    # for a risk is the Critical band — not merely "blocks work". A High risk
    # blocks work at score 15 and is serious, but flagging it high-potential
    # would put it alongside fatal-outcome near misses and dilute the flag.
    is_hipo = result.band == "Critical"

    return _finish(
        priority, is_hipo, recurring, record, trace,
        extra={
            "raw_score": result.raw_score, "adjusted_score": result.adjusted_score,
            "band": result.band, "approval_route": result.approval_route,
            "blocks_work": result.blocks_work,
        },
    )


# ══════════════════════════════════════════════════════════════════════════════

def _finish(priority, is_hipo, recurring, record, trace, extra=None) -> Assessment:
    """Apply the shared SLA and package the result."""
    clock_start = (
        getattr(record, "observed_date_time", None)
        or getattr(record, "reported_at", None)
        or datetime.utcnow()
    )
    days = _SLA_DAYS.get(priority)
    return Assessment(
        priority=priority,
        label=PRIORITY_LABELS.get(priority),
        is_hipo=bool(is_hipo),
        is_recurring=bool(recurring),
        requires_systemic_rca=bool(recurring),
        response_due_at=clock_start + timedelta(days=days) if days else None,
        min_investigator=_MIN_INVESTIGATOR.get(priority),
        trace=trace,
        explanation=" | ".join(trace),
        extra=extra or {},
    )


# ══════════════════════════════════════════════════════════════════════════════
# Hazard register
#
# The standing register (`hazards`), not the worker-reported hazard on
# `risk_reports` — that one is family `hazard` above and runs assess_risk.
#
# A register hazard is scored on the same 5x5 matrix, but its two axes are
# stored under different names and a different vocabulary: `probability` rather
# than likelihood, and a Low/Medium/High/Critical severity rather than the
# negligible..catastrophic scale `score_risk` knows. Translating here rather
# than widening SEVERITY keeps the shared table honest about what the words in
# it mean — "Low" is not a synonym for "negligible", it is the register's own
# four-point scale and lands on 2.
# ══════════════════════════════════════════════════════════════════════════════

_HAZARD_SEVERITY = {
    "low": 2, "medium": 3, "high": 4, "critical": 5,
    # The register form has always offered these four, but seed data and the
    # website catalog also carry the 5x5 words, so both resolve.
    "negligible": 1, "minor": 2, "moderate": 3, "major": 4, "catastrophic": 5,
}


def assess_hazard_register(db: Session, record) -> Assessment:
    """Stage 02 for a hazard on the standing register."""
    severity = _HAZARD_SEVERITY.get(str(getattr(record, "severity", "") or "").strip().lower())
    result = score_risk(
        likelihood=getattr(record, "probability", None),
        severity=severity,
        # A hazard is a standing condition, not a task, so none of the four
        # WF-01 uplifts (RAMS, new worker, night shift, temporary control)
        # applies to it. The raw L x S is the whole score.
        raw_score=getattr(record, "risk_score", None),
    )
    priority = _BAND_PRIORITY.get(result.band or "", "P5")
    recurring = _is_recurring(db, "hazards", record, "category_id")

    trace = [result.explanation or "Severity or probability not stated — unscored"]
    if recurring:
        trace.append("Same hazard category at this station within 12 months -> systemic review")

    exposed = getattr(record, "persons_exposed", None) or 0
    if exposed >= 5 and priority not in ("P1", "P2"):
        # Numbers exposed is a multiplier the L x S matrix does not carry. A
        # Medium hazard reaching a whole shift is not a Medium problem.
        trace.append(f"{exposed} people exposed -> priority raised one band")
        priority = {"P3": "P2", "P4": "P3", "P5": "P4"}.get(priority, priority)

    return _finish(
        priority, result.band == "Critical", recurring, record, trace,
        extra={
            "raw_score": result.raw_score, "band": result.band,
            "colour": result.colour, "review_frequency": result.review_frequency,
            "blocks_work": result.blocks_work,
        },
    )


def apply_to_hazard_register(record, assessment: Optional[Assessment]) -> None:
    """Write an assessment onto a `hazards` row. Caller commits.

    Separate from `apply_to` because the register carries only the four shared
    assessment columns from migration 066 — it has no is_hipo, min_investigator
    or assessment_trace. Calling the generic writer would raise on the first
    missing attribute.
    """
    if assessment is None:
        return
    record.assessed_priority = assessment.priority
    record.assessed_label = assessment.label
    record.response_due_at = assessment.response_due_at
    record.risk_score = assessment.extra.get("raw_score")
    # datetime.now(), not utcnow(): every other timestamp on `hazards` is
    # written by hazard_register in local time. Mixing the two put the
    # assessment five hours before the log it followed, which sorted it to the
    # top of the trail and made the hazard look assessed before it existed.
    record.assessed_at = datetime.now()


ASSESSORS = {
    "near_miss": assess_near_miss,
    "unsafe_act": assess_unsafe_act,
    "risk": assess_risk,
    "hazard": assess_risk,
    "hazard_register": assess_hazard_register,
}


def assess(db: Session, event_family: str, record) -> Optional[Assessment]:
    """Run stage 02 for this event family.

    Incidents are deliberately absent: they are assessed by
    `app.controllers.incident_workflow._apply_severity_and_statutory`, which
    also resolves statutory reportability against the site's jurisdiction.
    Routing them here as well would classify the same record twice.
    """
    fn = ASSESSORS.get((event_family or "").strip().lower())
    return fn(db, record) if fn else None


def apply_to(record, assessment: Optional[Assessment]) -> None:
    """Write an assessment onto the shared columns. Caller commits."""
    if assessment is None:
        return
    record.assessed_priority = assessment.priority
    record.assessed_label = assessment.label
    record.is_hipo = int(assessment.is_hipo)
    record.is_recurring_pattern = int(assessment.is_recurring)
    record.requires_systemic_rca = int(assessment.requires_systemic_rca)
    record.response_due_at = assessment.response_due_at
    record.min_investigator = assessment.min_investigator
    record.assessment_trace = assessment.explanation
    record.assessed_at = datetime.utcnow()
