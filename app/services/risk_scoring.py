"""WF-01 risk scoring — L x S, the four mandatory uplifts, and band assignment.

Source: EHSERA AI Orchestration Platform ISMS v1.0, WF-01 steps 3-5 and 8, and
the "Risk Scoring Matrix (L x S)" / "Risk Band Definitions & Review Frequency"
reference tables.

The uplifts are the point of this module. A raw L x S of 12 is Medium and needs
nothing more than a supervisor. The same task at night, by a worker with under
30 days' service, with no RAMS linked, is 12 + 2 + 1 + 1 = 16 — High, and work
cannot proceed without Safety Manager approval. Scoring L x S alone silently
loses that escalation, which is what the platform was previously doing.

Pure functions — no DB, no I/O. Per the spec's engine assignment this is L2
Rules Engine throughout: "Four boolean checks and one addition. No LLM ever."
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ══════════════════════════════════════════════════════════════════════════════
# WF-01 · Risk score
#
#   Raw       = Likelihood (1-5) x Severity (1-5)          -> 1-25
#   Uplifts   = +2 no valid RAMS linked
#               +1 worker with <30 days' service
#               +1 night shift (22:00-06:00)
#               +1 temporary control substituted
#   Adjusted  = min(raw + uplifts, 25)
#
#   1-6   Low       Green   annual review,     Supervisor sign-off
#   7-14  Medium    Amber   6-monthly review,  Safety Manager approval
#   15-20 High      Orange  quarterly review,  Safety Manager approval, work blocked
#   21-25 Critical  Red     monthly review,    Executive sign-off, work blocked
# ══════════════════════════════════════════════════════════════════════════════

MAX_SCORE = 25

BAND_LOW = "Low"
BAND_MEDIUM = "Medium"
BAND_HIGH = "High"
BAND_CRITICAL = "Critical"

# Thresholds the rest of the platform routes on. Named because they appear in
# WF-01 step 8 and again in the permit gate.
HIGH_THRESHOLD = 15        # >= 15 blocks work pending Safety Manager approval
CRITICAL_THRESHOLD = 21    # >= 21 requires Executive sign-off

_BANDS = (
    # (min_score, band, colour, review_frequency, approval_route, blocks_work)
    (21, BAND_CRITICAL, "Red", "Monthly", "Executive", True),
    (15, BAND_HIGH, "Orange", "Quarterly", "Safety Manager", True),
    (7, BAND_MEDIUM, "Amber", "6-monthly", "Safety Manager", False),
    (1, BAND_LOW, "Green", "Annual", "Supervisor", False),
)

# ── The four mandatory uplifts, in spec order ────────────────────────────────
UPLIFTS = (
    ("no_valid_rams", 2, "No valid RAMS linked"),
    ("new_worker", 1, "Worker with under 30 days' service"),
    ("night_shift", 1, "Night shift (22:00-06:00)"),
    ("temporary_control", 1, "Temporary control substituted"),
)

# 5x5 matrix vocabulary. Kept here so the API, the mobile form and the gate
# engine all resolve the same words to the same integers.
LIKELIHOOD = {
    "rare": 1, "unlikely": 2, "possible": 3, "likely": 4, "almost_certain": 5,
    "almost certain": 5,
}
SEVERITY = {
    "negligible": 1, "minor": 2, "moderate": 3, "major": 4, "critical": 5,
    # `risk_reports` calls this column "consequence" and the seed data uses
    # "catastrophic" for the top band.
    "catastrophic": 5,
}


@dataclass
class RiskResult:
    raw_score: Optional[int]
    adjusted_score: Optional[int]
    uplift_total: int
    uplifts_applied: List[str]              # human-readable audit trail
    band: Optional[str]
    colour: Optional[str]
    review_frequency: Optional[str]
    approval_route: Optional[str]
    blocks_work: bool
    capped: bool                            # True if uplifts were clipped at 25
    explanation: str = ""

    def to_dict(self) -> Dict:
        return {
            "raw_score": self.raw_score,
            "adjusted_score": self.adjusted_score,
            "uplift_total": self.uplift_total,
            "uplifts_applied": self.uplifts_applied,
            "band": self.band,
            "colour": self.colour,
            "review_frequency": self.review_frequency,
            "approval_route": self.approval_route,
            "blocks_work": self.blocks_work,
            "explanation": self.explanation,
        }


def resolve_likelihood(value) -> Optional[int]:
    """Accept either the word or the number the client already sends."""
    return _resolve(value, LIKELIHOOD)


def resolve_severity(value) -> Optional[int]:
    return _resolve(value, SEVERITY)


def _resolve(value, table: Dict[str, int]) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value if 1 <= value <= 5 else None
    key = str(value).strip().lower()
    if key.isdigit():
        n = int(key)
        return n if 1 <= n <= 5 else None
    return table.get(key)


def risk_band(score: Optional[int]) -> tuple:
    """(band, colour, review_frequency, approval_route, blocks_work) for a score."""
    if score is None:
        return (None, None, None, None, False)
    for minimum, band, colour, review, route, blocks in _BANDS:
        if score >= minimum:
            return (band, colour, review, route, blocks)
    return (None, None, None, None, False)


def score_risk(
    likelihood=None,
    severity=None,
    raw_score: Optional[int] = None,
    no_valid_rams: bool = False,
    new_worker: bool = False,
    night_shift: bool = False,
    temporary_control: bool = False,
) -> RiskResult:
    """Score a risk and apply the four mandatory WF-01 uplifts.

    Pass either `likelihood` + `severity` (words or 1-5 integers), or a
    pre-computed `raw_score`. If both are given, the explicit raw_score wins —
    that is what the mobile app posts when it has already done the arithmetic.

    An unresolvable likelihood/severity yields a result with `raw_score=None`
    rather than a guess, so the caller can reject the submission.
    """
    if raw_score is None:
        l = resolve_likelihood(likelihood)
        s = resolve_severity(severity)
        raw_score = l * s if l and s else None

    if raw_score is not None and not (1 <= raw_score <= MAX_SCORE):
        # WF-01 step 3 escalation: "Score outside 1-25 -> reject as data entry error."
        raw_score = None

    if raw_score is None:
        return RiskResult(
            raw_score=None, adjusted_score=None, uplift_total=0, uplifts_applied=[],
            band=None, colour=None, review_frequency=None, approval_route=None,
            blocks_work=False, capped=False,
            explanation="Likelihood x Severity could not be resolved to a 1-25 score.",
        )

    flags = {
        "no_valid_rams": no_valid_rams,
        "new_worker": new_worker,
        "night_shift": night_shift,
        "temporary_control": temporary_control,
    }

    uplift_total = 0
    applied: List[str] = []
    for key, points, label in UPLIFTS:
        if flags[key]:
            uplift_total += points
            applied.append(f"+{points} {label}")

    uncapped = raw_score + uplift_total
    adjusted = min(uncapped, MAX_SCORE)
    band, colour, review, route, blocks = risk_band(adjusted)

    detail = f"{raw_score}"
    if applied:
        detail += " " + " ".join(applied) + f" = {uncapped}"
        if uncapped > MAX_SCORE:
            detail += f", capped at {MAX_SCORE}"
    explanation = (
        f"Risk = L x S = {detail} -> {adjusted} ({band}). "
        f"{review} review, {route} sign-off."
        + (" Work blocked until approved." if blocks else "")
    )

    return RiskResult(
        raw_score=raw_score,
        adjusted_score=adjusted,
        uplift_total=uplift_total,
        uplifts_applied=applied,
        band=band,
        colour=colour,
        review_frequency=review,
        approval_route=route,
        blocks_work=blocks,
        capped=uncapped > MAX_SCORE,
        explanation=explanation,
    )
