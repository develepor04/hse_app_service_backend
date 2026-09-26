"""WF-05 · how findings are classified and scored.

The auditor judges each item, the system does the arithmetic. Two specifications
express the formula differently and they are mathematically identical — a full
conformance is worth twice an observation:

    ALGO-ISMS-WF-2026-v1.0 (point rubric)
        full compliance      = 2 pts
        partial/observation  = 1 pt
        non-compliance       = 0 pts
        score = (points earned / points possible) x 100

    AUD-FORM-01 (form specification)
        score = (C + 0.5 x OBS) / total assessed x 100

Items marked Not Applicable are excluded from the denominator, so a score is
never diluted by questions that did not apply to that site.

Nothing here writes to the database. The controller owns persistence; this module
owns the judgement rules, which is what makes them testable in isolation.
"""
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional


# ══════════════════════════════════════════════════════════════════════════════
# Responses and the point rubric
# ══════════════════════════════════════════════════════════════════════════════

FULL = "full"
PARTIAL = "partial"
NONE = "none"
NA = "na"

POINTS: Dict[str, int] = {FULL: 2, PARTIAL: 1, NONE: 0}
POINTS_POSSIBLE = 2

# The old vocabulary the mobile app and the seeded checklists still speak. A
# pass/fail answer carries no middle term, so it maps onto the two ends of the
# rubric and an audit submitted by an old client still scores correctly.
_LEGACY = {
    "pass": FULL,
    "compliant": FULL,
    "fail": NONE,
    "non_compliant": NONE,
    "partial": PARTIAL,
    "observation": PARTIAL,
    "n/a": NA,
    "not_applicable": NA,
}


def normalise_response(value: Optional[str]) -> Optional[str]:
    """Accept either vocabulary, return the rubric one. None means unanswered."""
    if value is None:
        return None
    v = str(value).strip().lower()
    if not v:
        return None
    if v in POINTS or v == NA:
        return v
    return _LEGACY.get(v)


# ══════════════════════════════════════════════════════════════════════════════
# The five finding classifications
# ══════════════════════════════════════════════════════════════════════════════

CONFORMANCE = "conformance"
OBSERVATION = "observation"
MINOR_NC = "minor_nc"
MAJOR_NC = "major_nc"
CRITICAL = "critical"

CLASSIFICATIONS: Dict[str, dict] = {
    CONFORMANCE: {
        "label": "Conformance",
        "meaning": "Meets the requirement. Scored as a positive — audits record what is working, not only what is wrong.",
        "severity": 0,
        "action_days": None,
    },
    OBSERVATION: {
        "label": "Observation",
        "meaning": "Compliant but improvable. Raises a finding, but not a non-conformance.",
        "severity": 1,
        "action_days": None,
    },
    MINOR_NC: {
        "label": "Minor NC",
        "meaning": "A lapse that does not undermine the system. Triggered automatically when a section falls below 60%.",
        "severity": 2,
        "action_days": 30,
    },
    MAJOR_NC: {
        "label": "Major NC",
        "meaning": "A systemic failure. Triggered automatically when any critical item scores zero. "
                   "Safety Manager notified within 24 hours, corrective action required within 7 days.",
        "severity": 3,
        "action_days": 7,
    },
    CRITICAL: {
        "label": "Critical / Regulatory",
        "meaning": "Immediate danger or a legal breach. Executive notified at once and work may be suspended.",
        "severity": 4,
        "action_days": 1,
    },
}

# What a response classifies as before the auditor exercises judgement. The
# auditor owns the final call on every finding — this is the default the app
# shows, not the answer.
DEFAULT_CLASSIFICATION = {
    FULL: CONFORMANCE,
    PARTIAL: OBSERVATION,
    NONE: MINOR_NC,
}


def default_classification(response: Optional[str], is_critical: bool = False) -> Optional[str]:
    """The classification an answer starts at.

    A critical item scoring zero is a Major NC by rule, not by judgement — the
    auditor can escalate it to Critical but cannot quietly downgrade it, which is
    the point of marking an item critical in the first place.
    """
    r = normalise_response(response)
    if r is None or r == NA:
        return None
    if is_critical and r == NONE:
        return MAJOR_NC
    return DEFAULT_CLASSIFICATION.get(r)


def is_non_conformance(classification: Optional[str]) -> bool:
    return classification in (MINOR_NC, MAJOR_NC, CRITICAL)


# ══════════════════════════════════════════════════════════════════════════════
# Score bands
# ══════════════════════════════════════════════════════════════════════════════

EXCELLENT = "excellent"
GOOD = "good"
ACCEPTABLE = "acceptable"
POOR = "poor"

SCORE_BANDS = [
    (90, EXCELLENT, "Excellent", "90% and above"),
    (75, GOOD, "Good", "75 – 89%"),
    (60, ACCEPTABLE, "Acceptable", "60 – 74%"),
    (0, POOR, "Poor", "Below 60%"),
]

# Below 70% automatically alerts the Safety Manager.
ALERT_THRESHOLD = 70
# Below 65% twice in a row forces a re-audit.
RE_AUDIT_THRESHOLD = 65


def score_band(score: Optional[float]) -> str:
    if score is None:
        return POOR
    for floor, key, _label, _range in SCORE_BANDS:
        if score >= floor:
            return key
    return POOR


def band_label(band: str) -> str:
    for _floor, key, label, _range in SCORE_BANDS:
        if key == band:
            return label
    return band.title()


# ══════════════════════════════════════════════════════════════════════════════
# Overall rating — set by finding counts, not by the score
# ══════════════════════════════════════════════════════════════════════════════

SATISFACTORY = "satisfactory"
REQUIRES_IMPROVEMENT = "requires_improvement"
UNSATISFACTORY = "unsatisfactory"

# More than three Minor NCs makes the audit Requires Improvement.
MINOR_NC_LIMIT = 3


def overall_rating(counts: Dict[str, int]) -> str:
    """"The overall rating is set separately from the finding counts."

    A high percentage with one Major non-conformance in it is still an
    unsatisfactory audit, which is why this does not read the score at all.
    """
    if counts.get(CRITICAL, 0) or counts.get(MAJOR_NC, 0):
        return UNSATISFACTORY
    if counts.get(MINOR_NC, 0) > MINOR_NC_LIMIT:
        return REQUIRES_IMPROVEMENT
    return SATISFACTORY


# ══════════════════════════════════════════════════════════════════════════════
# The calculation
# ══════════════════════════════════════════════════════════════════════════════

# A section scoring below this raises a Minor NC of its own.
SECTION_NC_THRESHOLD = 60


@dataclass
class SectionScore:
    section: str
    points_earned: int
    points_possible: int
    assessed: int
    score: float
    below_threshold: bool


@dataclass
class ScoreResult:
    score: float
    band: str
    band_label: str
    points_earned: int
    points_possible: int
    assessed: int
    not_applicable: int
    unanswered: int
    sections: List[SectionScore] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)
    overall_rating: str = SATISFACTORY
    explanation: str = ""

    @property
    def sections_below_threshold(self) -> List[SectionScore]:
        return [s for s in self.sections if s.below_threshold]


def _item_response(item) -> Optional[str]:
    return normalise_response(getattr(item, "response", None))


def score_items(items: Iterable) -> ScoreResult:
    """Run the rubric over a checklist.

    Accepts anything with `response`, `section`, `is_critical` and
    `classification` attributes, so ORM rows and inbound payload objects both
    work without a conversion step.
    """
    items = list(items)

    earned = possible = assessed = na = unanswered = 0
    per_section: Dict[str, List[int]] = {}

    for it in items:
        r = _item_response(it)
        if r is None:
            unanswered += 1
            continue
        if r == NA:
            na += 1
            continue
        pts = POINTS[r]
        earned += pts
        possible += POINTS_POSSIBLE
        assessed += 1
        key = (getattr(it, "section", None) or "General").strip() or "General"
        bucket = per_section.setdefault(key, [0, 0, 0])
        bucket[0] += pts
        bucket[1] += POINTS_POSSIBLE
        bucket[2] += 1

    score = round(earned / possible * 100, 1) if possible else 0.0

    sections = [
        SectionScore(
            section=name,
            points_earned=e,
            points_possible=p,
            assessed=n,
            score=round(e / p * 100, 1) if p else 0.0,
            below_threshold=bool(p) and (e / p * 100) < SECTION_NC_THRESHOLD,
        )
        for name, (e, p, n) in sorted(per_section.items())
    ]

    counts = {k: 0 for k in CLASSIFICATIONS}
    for it in items:
        c = getattr(it, "classification", None) or default_classification(
            getattr(it, "response", None), bool(getattr(it, "is_critical", False))
        )
        if c in counts:
            counts[c] += 1

    return ScoreResult(
        score=score,
        band=score_band(score),
        band_label=band_label(score_band(score)),
        points_earned=earned,
        points_possible=possible,
        assessed=assessed,
        not_applicable=na,
        unanswered=unanswered,
        sections=sections,
        counts=counts,
        overall_rating=overall_rating(counts),
        explanation=(
            f"({earned} earned / {possible} possible) x 100 = {score}% "
            f"({band_label(score_band(score))}); {na} item(s) not applicable and excluded"
        ),
    )


def action_due_days(classification: str) -> Optional[int]:
    """How long the corrective action for this classification has."""
    return CLASSIFICATIONS.get(classification, {}).get("action_days")


def rubric_reference() -> dict:
    """The whole rubric, shipped to the app so the phone explains itself offline."""
    return {
        "points": {"full": 2, "partial": 1, "none": 0, "na": "excluded"},
        # Both specifications, because the app shows the rubric to the auditor and
        # the two documents state it differently. They are the same arithmetic —
        # a full conformance is worth twice an observation either way — and an
        # auditor holding one document should recognise what the phone shows.
        "formula": "(points earned / points possible) x 100",
        "formula_alt": "(C + 0.5 x OBS) / total assessed x 100",
        "formula_note": (
            "The algorithmic spec and the form spec express this differently and are "
            "mathematically identical."
        ),
        "bands": [
            {"key": key, "label": label, "range": rng, "floor": floor}
            for floor, key, label, rng in SCORE_BANDS
        ],
        "alert_threshold": ALERT_THRESHOLD,
        "re_audit_threshold": RE_AUDIT_THRESHOLD,
        "section_nc_threshold": SECTION_NC_THRESHOLD,
        "minor_nc_limit": MINOR_NC_LIMIT,
        "classifications": [
            {"key": k, **v} for k, v in CLASSIFICATIONS.items()
        ],
        "ratings": {
            SATISFACTORY: "No non-conformance above a minor lapse.",
            REQUIRES_IMPROVEMENT: f"More than {MINOR_NC_LIMIT} Minor NCs.",
            UNSATISFACTORY: "Any Major non-conformance or regulatory breach.",
        },
    }
