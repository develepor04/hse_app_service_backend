"""WF-04 CAPA prioritisation — priority score, band, and due date.

Source: EHSERA AI Orchestration Platform ISMS v1.0, WF-04 "CAPA Priority Matrix
(Severity Potential x Systemic Risk)" and "CAPA Type Due Date Rules".

Two independent things, deliberately kept separate because the spec defines them
separately and they answer different questions:

  · priority_score = severity_potential x systemic_risk  (1-9)
    "how important is this action" — drives the Standard/High/Critical band and
    therefore review attention.

  · capa_type (P1-P5) -> target completion  (24h .. 90 days)
    "how fast must it be done" — driven by what triggered the CAPA, not by the
    matrix. A P1 immediate action is due in 24 hours even if its matrix score is
    low, because a regulatory breach is time-critical regardless.

Pure functions. This is L2 Rules Engine per the spec — multiplication and a
lookup, no inference.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional


# ══════════════════════════════════════════════════════════════════════════════
# WF-04 · Priority matrix
#
#   score = severity_potential (1-3) x systemic_risk (1-3)
#
#   1-3  Standard      6    High
#   4    High          9    Critical
# ══════════════════════════════════════════════════════════════════════════════

BAND_STANDARD = "Standard"
BAND_HIGH = "High"
BAND_CRITICAL = "Critical"

LEVELS = {"low": 1, "medium": 2, "high": 3}

# The spec's matrix, transcribed cell by cell rather than derived from the
# product, so the table in the document can be diffed against the code.
_MATRIX = {
    (1, 1): (1, BAND_STANDARD), (1, 2): (2, BAND_STANDARD), (1, 3): (3, BAND_STANDARD),
    (2, 1): (2, BAND_STANDARD), (2, 2): (4, BAND_HIGH),     (2, 3): (6, BAND_HIGH),
    (3, 1): (3, BAND_STANDARD), (3, 2): (6, BAND_HIGH),     (3, 3): (9, BAND_CRITICAL),
}

# ── CAPA type due-date rules ────────────────────────────────────────────────
CAPA_TYPES: Dict[str, dict] = {
    "P1": {"label": "Immediate", "hours": 24,        "trigger": "Critical incident or regulatory breach",
           "evidence": "Immediate control documented"},
    "P2": {"label": "Urgent",    "hours": 7 * 24,    "trigger": "LTI or major non-conformance",
           "evidence": "Corrective action physically implemented and verified"},
    "P3": {"label": "High",      "hours": 30 * 24,   "trigger": "MTC or minor non-conformance",
           "evidence": "Evidence type matches CAPA type (photo/document/training record)"},
    "P4": {"label": "Medium",    "hours": 60 * 24,   "trigger": "Near miss or observation",
           "evidence": "Relevant to stated success criteria"},
    "P5": {"label": "Low",       "hours": 90 * 24,   "trigger": "Proactive improvement",
           "evidence": "Reviewed by independent Safety Engineer"},
}

# An incident-triggered CAPA inherits the incident's P1-P5 severity directly —
# the two scales are the same vocabulary and the spec's trigger column lines up
# ("Critical incident" -> P1, "LTI" -> P2, "MTC" -> P3, "Near miss" -> P4).
INCIDENT_PRIORITY_TO_CAPA_TYPE = {"P1": "P1", "P2": "P2", "P3": "P3", "P4": "P4", "P5": "P5"}


def _level(value, default: Optional[int] = None) -> Optional[int]:
    """Accept 'low'/'medium'/'high' or 1/2/3."""
    if value is None:
        return default
    if isinstance(value, int):
        return value if 1 <= value <= 3 else default
    key = str(value).strip().lower()
    if key.isdigit():
        n = int(key)
        return n if 1 <= n <= 3 else default
    return LEVELS.get(key, default)


@dataclass
class CapaPriorityResult:
    severity_potential: Optional[int]
    systemic_risk: Optional[int]
    priority_score: Optional[int]
    priority_band: Optional[str]
    capa_type: Optional[str]
    capa_type_label: Optional[str]
    target_hours: Optional[int]
    due_date: Optional[datetime]
    evidence_required: Optional[str]
    explanation: str = ""


def prioritise(
    severity_potential=None,
    systemic_risk=None,
    capa_type: Optional[str] = None,
    incident_priority: Optional[str] = None,
    created_at: Optional[datetime] = None,
) -> CapaPriorityResult:
    """Score a CAPA and compute its due date.

    `capa_type` (P1-P5) wins if given. Otherwise it is derived from
    `incident_priority` when the CAPA came from an incident. If neither is
    available the CAPA still gets a matrix score and band, but no due date —
    better than inventing a deadline.
    """
    sev = _level(severity_potential)
    sys_risk = _level(systemic_risk)

    score, band = (None, None)
    if sev is not None and sys_risk is not None:
        score, band = _MATRIX[(sev, sys_risk)]

    ctype = (capa_type or "").strip().upper() or None
    if ctype not in CAPA_TYPES:
        ctype = INCIDENT_PRIORITY_TO_CAPA_TYPE.get((incident_priority or "").strip().upper())

    spec = CAPA_TYPES.get(ctype) if ctype else None
    base = created_at or datetime.utcnow()
    due = base + timedelta(hours=spec["hours"]) if spec else None

    parts = []
    if score is not None:
        parts.append(f"Priority = severity {sev} x systemic {sys_risk} = {score} ({band})")
    else:
        parts.append("Priority not scored — severity potential or systemic risk not supplied")
    if spec:
        window = f"{spec['hours']}h" if spec["hours"] < 48 else f"{spec['hours'] // 24} days"
        parts.append(f"{ctype} {spec['label']} — due in {window}")
    else:
        parts.append("No CAPA type — due date not set")

    return CapaPriorityResult(
        severity_potential=sev,
        systemic_risk=sys_risk,
        priority_score=score,
        priority_band=band,
        capa_type=ctype,
        capa_type_label=spec["label"] if spec else None,
        target_hours=spec["hours"] if spec else None,
        due_date=due,
        evidence_required=spec["evidence"] if spec else None,
        explanation=". ".join(parts) + ".",
    )
