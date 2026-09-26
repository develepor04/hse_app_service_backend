"""WF-04 · the CAPA lifecycle rules.

Source: HSE_CAPA_Lifecycle.pdf Rev 5.0 — "The Complete CAPA Lifecycle, From
Raising to Closure". Ten steps, six roles, three closure gates.

Everything here is a pure function over a CAPA row. No database writes, no HTTP.
The controller decides *who* may act; this module decides *whether the action is
allowed and what it produces*, so both the API and the scheduler get the same
answers rather than each re-deriving them.

The document's central claim, and the one thing the previous implementation got
backwards:

    Marking an action complete does not close it.

So `Completed` is no longer a terminal state reachable in one call. The owner
submits evidence, the system validates it, an independent reviewer confirms it,
and only then is the Safety Manager offered the approval.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time as dt_time, timedelta
from typing import Any, Dict, List, Optional


# ══════════════════════════════════════════════════════════════════════════════
# The state machine
# ══════════════════════════════════════════════════════════════════════════════
#
# Legacy rows use `Open`, `In Progress`, `Completed` and `Overdue`. The first two
# keep their exact meaning. `Completed` becomes a legacy terminal status — new
# rows finish at `Closed` — and `Overdue` is dropped as a *status*, because
# overdue is a property of the due date, not a state: an action that is both
# in-progress and late used to lose the fact that anyone was working on it.

OPEN = "Open"
IN_PROGRESS = "In Progress"
EVIDENCE_SUBMITTED = "Evidence Submitted"
PENDING_REVIEW = "Pending Review"
PENDING_APPROVAL = "Pending Approval"
CLOSED = "Closed"

# Terminal statuses, including the legacy spellings already in the table. Every
# "is this action still open" filter in the codebase already excludes this set,
# which is why the new terminal status is `Closed` rather than something novel.
TERMINAL = {"closed", "completed", "verified", "done"}

# step -> the status the action sits in while that step is outstanding
STATUS_STEP = {
    OPEN: 5,                 # 05 assigned, not started
    IN_PROGRESS: 6,          # 06 implementation
    EVIDENCE_SUBMITTED: 7,   # 07 evidence uploaded, awaiting validation
    PENDING_REVIEW: 8,       # 08 closure validation / independent review
    PENDING_APPROVAL: 10,    # 10 awaiting the Safety Manager
    CLOSED: 10,
    # Legacy. `Overdue` was a status in the old vocabulary, which lost the fact
    # that someone was working on it — lateness is a property of the due date,
    # not a state. Existing rows still carry it, so it reads as implementation.
    "Overdue": 6,
    "Completed": 10,
}

STEP_LABELS = {
    1: "CAPA created", 2: "Root cause linked", 3: "Action planned",
    4: "Priority assigned", 5: "Owner notified", 6: "Implementation",
    7: "Evidence uploaded", 8: "Closure validation", 9: "Effectiveness review",
    10: "Approval & archive",
}


def is_terminal(status: Optional[str]) -> bool:
    return (status or "").strip().lower() in TERMINAL


# ══════════════════════════════════════════════════════════════════════════════
# Step 03 · planning rules
# ══════════════════════════════════════════════════════════════════════════════

# What kind of proof each category of action has to produce. This is the table
# CHECK 1 enforces: "a training action needs a training record; a physical fix
# needs a photo or inspection confirmation."
EVIDENCE_TYPES = (
    "photo", "document", "training_record", "test_report", "inspection_confirmation",
)

ACTION_CATEGORIES: Dict[str, Dict[str, Any]] = {
    "physical_fix": {
        "label": "Physical fix",
        "evidence": ("photo", "inspection_confirmation"),
    },
    "procedure_change": {
        "label": "Procedure or document change",
        "evidence": ("document",),
    },
    "training": {
        "label": "Training or competence",
        "evidence": ("training_record",),
    },
    "inspection": {
        "label": "Inspection or monitoring",
        "evidence": ("inspection_confirmation", "photo"),
    },
    "test": {
        "label": "Test or commissioning",
        "evidence": ("test_report", "document"),
    },
    # Deliberately permissive. An action nobody could categorise should not be
    # blocked from closing — it should be visible as uncategorised, which the
    # planning response reports.
    "other": {
        "label": "Other",
        "evidence": EVIDENCE_TYPES,
    },
}

# "CAPA by hierarchy of control", from the workflow slide and the stage 05
# description. Ordered strongest first — the order is the point.
HIERARCHY_LEVELS = (
    "elimination", "substitution", "engineering", "administrative", "ppe",
)

# Bands whose plan a manager must approve before work starts (step 03).
PLAN_APPROVAL_BANDS = {"High", "Critical"}


def allowed_evidence_types(action_category: Optional[str]) -> tuple:
    spec = ACTION_CATEGORIES.get((action_category or "other").strip().lower())
    return tuple(spec["evidence"]) if spec else EVIDENCE_TYPES


def requires_plan_approval(priority_band: Optional[str]) -> bool:
    return (priority_band or "") in PLAN_APPROVAL_BANDS


@dataclass
class PlanValidation:
    ok: bool
    errors: List[str] = field(default_factory=list)


def validate_plan(
    action_plan: Optional[str],
    success_criteria: Optional[str],
    action_category: Optional[str],
    due_date,
    created_at: Optional[datetime],
    target_hours: Optional[int],
) -> PlanValidation:
    """Step 03. The system "blocks submission if success criteria are empty or
    the due date exceeds the maximum allowed for that type"."""
    errors: List[str] = []

    if not (action_plan or "").strip():
        errors.append("An action plan is required — describe the specific action and the resources needed.")
    if not (success_criteria or "").strip():
        errors.append(
            "Success criteria are required. Without them there is nothing for the "
            "evidence to be measured against at closure."
        )

    cat = (action_category or "").strip().lower()
    if cat and cat not in ACTION_CATEGORIES:
        errors.append(
            f"Unknown action category '{action_category}'. Expected one of: "
            + ", ".join(ACTION_CATEGORIES)
        )

    # The due date may not run past the window the CAPA type allows. A P1 action
    # given 30 days is not a P1 action.
    if due_date and target_hours and created_at:
        latest = (created_at + timedelta(hours=target_hours)).date()
        d = due_date.date() if isinstance(due_date, datetime) else due_date
        if d > latest:
            errors.append(
                f"Due date {d} is past the maximum for this CAPA type — "
                f"the deadline may not be later than {latest}."
            )

    return PlanValidation(ok=not errors, errors=errors)


# ══════════════════════════════════════════════════════════════════════════════
# Step 07 · evidence validation
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class EvidenceValidation:
    accepted: bool
    reason: Optional[str] = None


def validate_evidence(
    evidence_type: Optional[str],
    evidence_date: Optional[datetime],
    action_category: Optional[str],
    capa_created_at: Optional[datetime],
) -> EvidenceValidation:
    """Rejects the upload at the point of upload, per step 07.

    Two of the three closure checks are enforced here rather than only at
    closure, so the owner finds out immediately instead of at the final gate.
    """
    etype = (evidence_type or "").strip().lower()
    allowed = allowed_evidence_types(action_category)

    if etype not in EVIDENCE_TYPES:
        return EvidenceValidation(False, f"Unknown evidence type '{evidence_type}'. Allowed: {', '.join(EVIDENCE_TYPES)}.")
    if etype not in allowed:
        label = ACTION_CATEGORIES.get((action_category or "other").lower(), {}).get("label", action_category)
        return EvidenceValidation(
            False,
            f"A '{label}' action cannot be evidenced with a {etype.replace('_', ' ')}. "
            f"Allowed: {', '.join(t.replace('_', ' ') for t in allowed)}.",
        )
    if predates(evidence_date, capa_created_at):
        return EvidenceValidation(
            False,
            f"Evidence is dated {evidence_date:%Y-%m-%d}, before the action was raised "
            f"({capa_created_at:%Y-%m-%d}). It cannot show anything that changed as a result.",
        )
    return EvidenceValidation(True)


def predates(evidence_date, capa_created_at) -> bool:
    """Is this evidence from before the action existed?

    Compared by calendar date, not by timestamp. The check exists to catch
    "attaching a document or photo that already existed", which is a
    day-granularity question — and `capa_actions.created_at` is a MySQL
    CURRENT_TIMESTAMP in server-local time while the app writes UTC elsewhere,
    so a to-the-second comparison would reject a photo taken two hours before an
    action raised the same afternoon.
    """
    if not evidence_date or not capa_created_at:
        return False
    return evidence_date.date() < capa_created_at.date()


# ══════════════════════════════════════════════════════════════════════════════
# Step 08 · the three closure checks
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ClosureCheck:
    key: str
    label: str
    passed: bool
    detail: str


@dataclass
class ClosureValidation:
    passed: bool
    checks: List[ClosureCheck]

    def as_json(self) -> List[dict]:
        return [
            {"key": c.key, "label": c.label, "passed": c.passed, "detail": c.detail}
            for c in self.checks
        ]

    def failures(self) -> List[str]:
        return [c.detail for c in self.checks if not c.passed]


def run_closure_checks(
    *,
    action_category: Optional[str],
    capa_created_at: Optional[datetime],
    evidence_rows: List[Any],
    independent_review_result: Optional[str],
    independent_review_by: Optional[int],
    responsible_person_id: Optional[int],
) -> ClosureValidation:
    """"All three of these must pass before the Safety Manager is even offered
    the approval — and the system, not a person, decides whether they pass."

    `evidence_rows` are objects with evidence_type / evidence_date /
    validation_result attributes.
    """
    accepted = [
        e for e in evidence_rows
        if (getattr(e, "validation_result", None) or "").lower() != "rejected"
    ]

    # ── CHECK 1 · does the evidence match the action type ───────────────────
    allowed = allowed_evidence_types(action_category)
    matching = [e for e in accepted if (e.evidence_type or "").lower() in allowed]
    if not accepted:
        c1 = ClosureCheck(
            "evidence_type", "Evidence matches the action type", False,
            "No evidence has been attached.",
        )
    elif not matching:
        c1 = ClosureCheck(
            "evidence_type", "Evidence matches the action type", False,
            f"None of the attached evidence is of an allowed type "
            f"({', '.join(t.replace('_', ' ') for t in allowed)}).",
        )
    else:
        c1 = ClosureCheck(
            "evidence_type", "Evidence matches the action type", True,
            f"{len(matching)} matching item(s) attached.",
        )

    # ── CHECK 2 · is the evidence dated after the action was raised ─────────
    if not accepted:
        c2 = ClosureCheck(
            "evidence_date", "Evidence post-dates the action", False,
            "No evidence has been attached.",
        )
    else:
        stale = [e for e in accepted if predates(e.evidence_date, capa_created_at)]
        undated = [e for e in accepted if not e.evidence_date]
        if stale:
            c2 = ClosureCheck(
                "evidence_date", "Evidence post-dates the action", False,
                f"{len(stale)} item(s) are dated before the action was raised.",
            )
        elif undated:
            # An undated attachment cannot be shown to post-date anything, which
            # is exactly the false closure this check exists to catch.
            c2 = ClosureCheck(
                "evidence_date", "Evidence post-dates the action", False,
                f"{len(undated)} item(s) have no evidence date.",
            )
        else:
            c2 = ClosureCheck(
                "evidence_date", "Evidence post-dates the action", True,
                "All evidence is dated after the action was raised.",
            )

    # ── CHECK 3 · has an independent reviewer confirmed it ──────────────────
    result = (independent_review_result or "").strip().lower()
    if result != "confirmed":
        c3 = ClosureCheck(
            "independent_review", "Independently reviewed", False,
            "No independent reviewer has confirmed the action."
            if not result else "The independent reviewer rejected the evidence.",
        )
    elif (
        independent_review_by is not None
        and responsible_person_id is not None
        and independent_review_by == responsible_person_id
    ):
        # "An owner cannot sign off their own action."
        c3 = ClosureCheck(
            "independent_review", "Independently reviewed", False,
            "The action owner cannot be their own independent reviewer.",
        )
    else:
        c3 = ClosureCheck(
            "independent_review", "Independently reviewed", True,
            "Confirmed by an independent reviewer.",
        )

    checks = [c1, c2, c3]
    return ClosureValidation(passed=all(c.passed for c in checks), checks=checks)


# ══════════════════════════════════════════════════════════════════════════════
# The escalation timer chain
# ══════════════════════════════════════════════════════════════════════════════
#
# "Each stage fires on elapsed time as a proportion of the deadline, so it works
# identically for a 24-hour action and a 90-day one." Percentages, never absolute
# days — that is the whole design.

# threshold -> (who it goes to, what it says)
ESCALATION_CHAIN = (
    (50,  "owner_supervisor", "Halfway point — the Supervisor must confirm progress is real."),
    (75,  "owner",            "Three quarters of the time has gone. A quiet nudge, nobody else involved yet."),
    (90,  "supervisor",       "The owner's line manager is brought in while there is still time to intervene."),
    (100, "safety_manager",   "The deadline has passed. Escalated to the Safety Manager and flagged overdue."),
    (110, "executive",        "On the executive dashboard — a mandatory management review is triggered."),
)


def _now() -> datetime:
    """The clock that wrote `capa_actions.created_at`.

    That column is a MySQL CURRENT_TIMESTAMP, so it is in the database server's
    local time, while most of this codebase writes datetime.utcnow(). Comparing
    the two produced a *negative* elapsed percentage on a freshly raised action
    wherever the server is not on UTC — here it is UTC+5:30, so every new action
    read as -0.8% of its deadline and the 75% reminder would have fired five and
    a half hours late for the life of every P1.

    Local time is the right frame to standardise on rather than the other way
    round: `due_date` is a plain DATE the user picked in their own timezone, and
    the whole chain measures one against the other.
    """
    return datetime.now()


def elapsed_percent(
    created_at: Optional[datetime],
    due_date,
    now: Optional[datetime] = None,
) -> Optional[float]:
    """How far through its allotted time this action is, as a percentage.

    Returns None when there is no deadline to measure against — an action with
    no due date cannot be late, and inventing a percentage for it would put it
    on the overdue report forever.
    """
    if not created_at or not due_date:
        return None
    now = now or _now()
    # A date-typed deadline means end of that day, not the start of it. Using
    # midnight would make an action due today already 100% elapsed the moment
    # the day begins, escalating it to the Safety Manager before anyone has had
    # the working day the deadline was meant to grant.
    due = due_date if isinstance(due_date, datetime) else datetime.combine(due_date, dt_time.max)
    span = (due - created_at).total_seconds()
    if span <= 0:
        # Raised at or after its own deadline (a P1 backdated, typically). It is
        # immediately at 100%, not divided by zero.
        return 100.0
    return round(((now - created_at).total_seconds() / span) * 100.0, 1)


def due_escalations(
    created_at: Optional[datetime],
    due_date,
    already_fired: int = 0,
    now: Optional[datetime] = None,
) -> List[tuple]:
    """Which thresholds have been crossed but not yet notified.

    `already_fired` is the highest level previously recorded, so a job that runs
    hourly does not re-notify. Returns them in ascending order, which matters
    when an action passes several at once (a long-overdue one first seen by the
    scheduler should walk the whole chain, not jump to the end silently).
    """
    pct = elapsed_percent(created_at, due_date, now)
    if pct is None:
        return []
    return [
        (level, audience, message)
        for level, audience, message in ESCALATION_CHAIN
        if pct >= level and level > (already_fired or 0)
    ]


# ══════════════════════════════════════════════════════════════════════════════
# Step 09 · effectiveness reviews
# ══════════════════════════════════════════════════════════════════════════════

REVIEW_POINTS = (30, 60, 90)


def review_schedule(closed_at: datetime) -> List[tuple]:
    """The 30/60/90-day checks, scheduled from closure.

    Scheduled at closure rather than before it because the document has the
    system "reopen the action automatically if any fails" — you can only reopen
    something that closed. Blocking closure until day 90 would instead mean no
    action ever closes inside a quarter, which is not what the ageing report or
    the Control Integrity score assume.
    """
    return [(p, closed_at + timedelta(days=p)) for p in REVIEW_POINTS]


def review_verdict(
    has_recurred: Optional[bool],
    control_in_place: Optional[bool],
    root_cause_addressed: Optional[bool],
) -> str:
    """The document's three questions collapse to one verdict.

    Any single failure is a failure: a control still in place while the issue
    recurred means the control does not work, and a fixed symptom with an
    unaddressed root cause is the thing the systemic flag exists to catch.
    """
    if has_recurred is None and control_in_place is None and root_cause_addressed is None:
        return "pending"
    if has_recurred or control_in_place is False or root_cause_addressed is False:
        return "failed"
    return "passed"


# ══════════════════════════════════════════════════════════════════════════════
# Systemic issue detection
# ══════════════════════════════════════════════════════════════════════════════

SYSTEMIC_THRESHOLD = 3
SYSTEMIC_WINDOW_DAYS = 182  # six months


def describe(capa) -> dict:
    """Where this action is in the ten steps, for an API response."""
    status = capa.status or OPEN
    step = STATUS_STEP.get(status, 5)
    pct = elapsed_percent(capa.created_at, capa.due_date)
    return {
        "capa_ref": capa.capa_ref,
        "status": status,
        "step": step,
        "step_label": STEP_LABELS.get(step),
        "total_steps": 10,
        "is_closed": is_terminal(status),
        "elapsed_percent": pct,
        "is_overdue": bool(pct is not None and pct >= 100 and not is_terminal(status)),
        "escalation_level": capa.escalation_level or 0,
    }
