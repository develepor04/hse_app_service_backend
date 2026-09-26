"""WF-03 severity classification — the system-enforced P1-P5 decision tree.

Source: EHSERA AI Orchestration Platform ISMS v1.0, WF-03 "Severity Decision
Tree (System-Enforced)" and "Investigation SLA & Severity Matrix".

Severity is NOT a judgement call and NOT a dropdown. It is a decision tree over
facts the reporter already supplied: was anyone hurt, how were they treated, was
it a dangerous occurrence, and could it plausibly have killed someone. The same
facts must always produce the same priority, because the priority drives the
investigation SLA and — through app.services.statutory_reporting — the
regulator notification deadline.

Per the spec's engine assignment this is L2 Rules Engine: "Trained classifier on
structured incident fields" is listed as an *optional* ML enhancement, never the
primary path. Nothing here may be made probabilistic or AI-assisted.

Pure functions on purpose — no DB, no I/O. The one input that needs a database
(has this event type recurred at this site in 12 months?) is passed in as a
boolean by the caller, so this module stays testable in isolation.
"""
from dataclasses import dataclass, field
from typing import List, Optional


# ══════════════════════════════════════════════════════════════════════════════
# WF-03 · Severity Decision Tree
#
#   Q1  Was anyone injured or made ill?      No  -> Q3
#   Q2  Highest treatment level?             First aid only          -> P4
#                                            Medical treatment (MTC) -> P3
#                                            Hospitalisation / >3d   -> P2
#                                            Fatality / life-altering-> P1
#   Q3  Dangerous occurrence?                Yes -> P2 minimum
#   Q4  Worst-case potential fatal/multiple? Yes -> HIPO, P2 protocol
#   Q5  Same event type in 12 months here?   Yes -> recurring pattern flag
#
#   No injury and none of the above          -> P5 observation / near miss
# ══════════════════════════════════════════════════════════════════════════════

P1 = "P1"
P2 = "P2"
P3 = "P3"
P4 = "P4"
P5 = "P5"

# Ordered worst-first so `min(..., key=_RANK.get)` picks the more severe of two.
_RANK = {P1: 1, P2: 2, P3: 3, P4: 4, P5: 5}

PRIORITY_LABELS = {
    P1: "P1 — Fatal / Critical",
    P2: "P2 — Serious / LTI",
    P3: "P3 — Recordable (MTC)",
    P4: "P4 — First Aid / Observation",
    P5: "P5 — Near Miss / Observation",
}

# Q2 answers. The keys are what the mobile form posts; the values are the
# priority the spec assigns. Anything unrecognised falls through to None so a
# typo cannot silently downgrade an injury to P5.
TREATMENT_NONE = "none"
TREATMENT_FIRST_AID = "first_aid"
TREATMENT_MEDICAL = "medical_treatment"
TREATMENT_HOSPITALISATION = "hospitalisation"
TREATMENT_FATALITY = "fatality"

_TREATMENT_PRIORITY = {
    TREATMENT_FIRST_AID: P4,
    TREATMENT_MEDICAL: P3,
    TREATMENT_HOSPITALISATION: P2,
    TREATMENT_FATALITY: P1,
}

# Free-text spellings the app and the seed data already use, normalised onto the
# five canonical answers above. Kept deliberately narrow — an unknown string is
# better surfaced as "unclassified" than guessed at.
_TREATMENT_ALIASES = {
    "": TREATMENT_NONE,
    "none": TREATMENT_NONE,
    "no treatment": TREATMENT_NONE,
    "n/a": TREATMENT_NONE,
    "first aid": TREATMENT_FIRST_AID,
    "first aid only": TREATMENT_FIRST_AID,
    "first_aid": TREATMENT_FIRST_AID,
    "fac": TREATMENT_FIRST_AID,
    "medical": TREATMENT_MEDICAL,
    "medical treatment": TREATMENT_MEDICAL,
    "medical treatment beyond first aid": TREATMENT_MEDICAL,
    "mtc": TREATMENT_MEDICAL,
    "mti": TREATMENT_MEDICAL,
    "hospitalisation": TREATMENT_HOSPITALISATION,
    "hospitalization": TREATMENT_HOSPITALISATION,
    "hospital": TREATMENT_HOSPITALISATION,
    "lti": TREATMENT_HOSPITALISATION,
    "lost time": TREATMENT_HOSPITALISATION,
    "fatality": TREATMENT_FATALITY,
    "fatal": TREATMENT_FATALITY,
    "death": TREATMENT_FATALITY,
    "life-altering": TREATMENT_FATALITY,
    "life altering": TREATMENT_FATALITY,
}

# ── Investigation SLA & Severity Matrix ──────────────────────────────────────
# Days to close, and the minimum grade of investigator the spec requires.
_SLA = {
    P1: (30, "Safety Director"),
    P2: (15, "Safety Manager"),
    P3: (30, "Safety Advisor"),
    P4: (5, "Safety Team"),
    P5: (5, "Supervisor"),
}


def normalise_treatment(raw: Optional[str]) -> Optional[str]:
    """Map whatever the client sent onto one of the five canonical Q2 answers.

    Returns None for anything unrecognised so the caller can mark the record
    unclassified rather than assume the best case.
    """
    if raw is None:
        return TREATMENT_NONE
    key = str(raw).strip().lower()
    if key in _TREATMENT_PRIORITY or key == TREATMENT_NONE:
        return key
    return _TREATMENT_ALIASES.get(key)


@dataclass
class SeverityResult:
    priority: Optional[str]                 # P1..P5, or None if unclassifiable
    label: str
    is_hipo: bool                           # Q4 — high-potential incident
    is_recurring: bool                      # Q5 — same event type in 12 months
    is_dangerous_occurrence: bool           # Q3
    requires_systemic_rca: bool             # Q5 forces a systemic root cause
    investigation_days: Optional[int]
    min_investigator: Optional[str]
    trace: List[str] = field(default_factory=list)   # which questions decided it
    explanation: str = ""


def _more_severe(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """The worse of two priorities. None loses to any real priority."""
    candidates = [p for p in (a, b) if p is not None]
    if not candidates:
        return None
    return min(candidates, key=lambda p: _RANK[p])


def classify_severity(
    anyone_injured: bool,
    treatment_level: Optional[str] = None,
    days_away: Optional[int] = None,
    dangerous_occurrence: bool = False,
    worst_case_fatal: bool = False,
    recurring_event_type: bool = False,
) -> SeverityResult:
    """Run the WF-03 decision tree.

    `days_away` is an independent route to P2: the spec's Q2 reads
    "Hospitalisation **or >3 days lost**", and days-away is often known before
    the treatment level has been confirmed by a clinician.

    `recurring_event_type` must be supplied by the caller — see
    `app.controllers.incident_workflow` for the 12-month site lookup.
    """
    trace: List[str] = []
    priority: Optional[str] = None

    # ── Q1 / Q2 · injury path ────────────────────────────────────────────────
    if anyone_injured:
        trace.append("Q1: injured/ill = Yes -> Q2")
        level = normalise_treatment(treatment_level)
        if level is None:
            trace.append(
                f"Q2: treatment level {treatment_level!r} not recognised -> unclassified"
            )
        elif level == TREATMENT_NONE:
            # Injured but no treatment recorded yet. Do not guess — the spec has
            # no branch for it, and defaulting to P4 would understate a fatality
            # awaiting confirmation.
            trace.append("Q2: injury reported but no treatment level yet -> unclassified")
        else:
            priority = _TREATMENT_PRIORITY[level]
            trace.append(f"Q2: treatment = {level} -> {priority}")
    else:
        trace.append("Q1: injured/ill = No -> Q3")

    # >3 days lost is P2 regardless of how the treatment was coded.
    if days_away is not None and days_away > 3:
        upgraded = _more_severe(priority, P2)
        if upgraded != priority:
            trace.append(f"Q2: {days_away} days lost (>3) -> upgraded to P2")
        priority = upgraded

    # ── Q3 · dangerous occurrence ────────────────────────────────────────────
    if dangerous_occurrence:
        upgraded = _more_severe(priority, P2)
        trace.append(
            "Q3: dangerous occurrence = Yes -> P2 minimum"
            + (" (already higher)" if upgraded != P2 else "")
        )
        priority = upgraded
    elif not anyone_injured:
        trace.append("Q3: dangerous occurrence = No")

    # ── Q4 · worst-case potential (HIPO) ─────────────────────────────────────
    # The spec upgrades a *near miss* to the P2 investigation protocol. It does
    # not downgrade anything, so this only ever moves severity upward.
    is_hipo = bool(worst_case_fatal)
    if is_hipo:
        upgraded = _more_severe(priority, P2)
        if upgraded != priority:
            trace.append("Q4: worst-case fatal/multiple = Yes -> HIPO, P2 investigation protocol")
        else:
            trace.append("Q4: worst-case fatal/multiple = Yes -> HIPO flag (severity already >= P2)")
        priority = upgraded

    # ── Default · no injury, no dangerous occurrence, no HIPO ────────────────
    if priority is None and not anyone_injured:
        priority = P5
        trace.append("No injury, no dangerous occurrence -> P5 observation / near miss")

    # ── Q5 · recurrence ──────────────────────────────────────────────────────
    # Recurrence does not change the priority. It forces a systemic RCA, which
    # is a different and stronger obligation than a one-off investigation.
    if recurring_event_type:
        trace.append(
            "Q5: same event type at this site within 12 months -> recurring pattern, "
            "systemic root cause investigation mandatory"
        )

    days, investigator = _SLA.get(priority, (None, None))

    return SeverityResult(
        priority=priority,
        label=PRIORITY_LABELS.get(priority, "Unclassified — awaiting treatment detail"),
        is_hipo=is_hipo,
        is_recurring=bool(recurring_event_type),
        is_dangerous_occurrence=bool(dangerous_occurrence),
        requires_systemic_rca=bool(recurring_event_type),
        investigation_days=days,
        min_investigator=investigator,
        trace=trace,
        explanation=" | ".join(trace),
    )


def investigation_sla(priority: Optional[str]) -> tuple:
    """(days_to_close, minimum_investigator) for a priority. (None, None) if unknown."""
    return _SLA.get(priority, (None, None))
