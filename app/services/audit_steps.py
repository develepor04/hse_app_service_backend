"""WF-05 · the ten steps, and which one the audit is waiting on.

Read left to right for the sequence, top to bottom for the handover between
roles. Some steps are automatic — no human involved — and some are hard stops
where the audit cannot progress until a person acts or a condition is met.

    How this maps to the specification
    ──────────────────────────────────
    The client documents name several audit roles — Lead Auditor, Audit Team,
    Auditee Management, Safety Advisor, ISMS Director. Those are job titles in a
    large safety department, not app roles. On this platform they resolve to the
    four mobile roles plus web admin:

        Lead Auditor + Audit Team  ->  AUDITOR    one role; where several are
                                                  assigned to one audit, one is
                                                  designated lead
        Auditee Management         ->  SUPERVISOR the supervisor of the area
                                                  under audit
        Workers interviewed        ->  WORKER     observed and questioned during
                                                  the walk
        Safety Manager / Advisor   ->  SAFETY MANAGER  mobile only; alerted, but
                                                        owns no step in the audit
        ISMS Director / Safety Director -> WEB ADMIN    the web console, and every
                                                        step conducted on it

Step state is derived from the timestamps and rows the audit actually has, not
from a `current_step` column. A stored pointer drifts the moment anything is
written by a path that forgot to advance it, and the whole point of a hard stop
is that it cannot be skipped: "report issued" is true when a signature exists,
never because something set a number to 9.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

# Phases across the top of the ten-step table.
PLAN = "PLAN"
PREPARE = "PREPARE"
CONDUCT = "CONDUCT"
CLASSIFY = "CLASSIFY"
AGREE = "AGREE"
REPORT = "REPORT"
CLOSE = "CLOSE"

# Roles down the side — the platform's roles, not the document's job titles.
AUDITOR = "auditor"
WORKER = "worker"
SUPERVISOR = "supervisor"
SAFETY_MANAGER = "safety_manager"
ADMIN = "admin"
SYSTEM = "system"

ROLES: Dict[str, dict] = {
    AUDITOR: {
        "label": "Auditor",
        "surface": "Mobile",
        "summary": "Owns and conducts the audit.",
        "owns": [
            "Conducts the field inspection",
            "Collects and links evidence",
            "Classifies every finding",
            "Signs the report — nothing issues without it",
            "Verifies effectiveness at 30/60/90",
        ],
    },
    WORKER: {
        "label": "Worker",
        "surface": "Mobile",
        "summary": "The people being observed.",
        "owns": [
            "Interviewed and observed",
            "Shows competence and records",
            "Completes actions assigned to them",
            "Receives the toolbox talk",
        ],
    },
    SUPERVISOR: {
        "label": "Supervisor",
        "surface": "Mobile",
        "summary": "The area being audited.",
        "owns": [
            "Gets two weeks' notice",
            "Attends opening and closing",
            "Confirms factual accuracy",
            "Owns the actions for their area",
        ],
    },
    SAFETY_MANAGER: {
        "label": "Safety Manager",
        "surface": "Mobile",
        "summary": "Alerted, not an actor in the audit itself.",
        # Deliberately short. The specification gives this role the step-02 hard
        # stop and the report approval, but on this platform they are a mobile
        # role with no audit screens — so those sit with the Admin, who owns the
        # web console. What the Safety Manager genuinely receives today is the
        # alerting, which needs no screen to work.
        "owns": [
            "Notified immediately when a critical item scores zero",
            "Notified within 24 hours of any Major non-conformance",
            "Attends for serious findings",
        ],
    },
    ADMIN: {
        "label": "Admin",
        "surface": "Web console only",
        "summary": "Owns the whole programme. Every web-side step is theirs.",
        "owns": [
            "Maintains the checklist templates every audit runs from",
            "Maintains the auditor register",
            "Authorises the programme and generates the calendar",
            "Assigns an independent auditor — the step 02 hard stop",
            "Approves the report and owns distribution",
            "Owns the re-audit decision and cross-site trends",
        ],
    },
    SYSTEM: {
        "label": "The System",
        "surface": "Automatic",
        "summary": "No human involved.",
        "owns": [
            "Builds the schedule and brief",
            "Calculates scores and thresholds",
            "Raises actions from findings",
            "Fires the re-audit trigger",
        ],
    },
}


@dataclass(frozen=True)
class Step:
    number: int
    key: str
    phase: str
    label: str
    owner: str          # the role that has to act
    automatic: bool
    hard_stop: bool     # cannot progress until a person acts or a condition is met
    detail: str
    # What each other role does at this step, for the app's flow screen.
    role_notes: Dict[str, str]


STEPS: List[Step] = [
    Step(
        1, "schedule_generated", PLAN, "Schedule generated", SYSTEM, True, False,
        "Looks up the risk band to frequency, generates the year's events, notifies the auditee "
        "and sets a reminder 14 days out.",
        {
            ADMIN: "Authorises and approves the annual audit programme across all sites.",
            SYSTEM: "Looks up the risk band, generates the year's events and sets the reminders.",
        },
    ),
    Step(
        2, "team_assigned", PLAN, "Team assigned", ADMIN, False, True,
        "Names who audits what, and must ensure the auditor is independent of the area being "
        "audited. This is what makes the finding credible.",
        {
            AUDITOR: "Accepts the assignment. The audit appears in their queue and the "
                     "auto-generated brief pack arrives 7 days before. Where more than one "
                     "auditor is assigned, one is designated lead.",
            SUPERVISOR: "Notified in advance — minimum two weeks' notice, except for unannounced "
                        "inspections, which carry none by design.",
            ADMIN: "Maintains the auditor register and their qualifications.",
            SYSTEM: "Writes the brief. Pulls previous findings, open actions, current score and "
                    "overdue permits into a standard brief pack, 7 days before.",
        },
    ),
    Step(
        3, "pre_audit_prep", PREPARE, "Pre-audit prep", AUDITOR, False, False,
        "Reviews the brief before going out — previous findings and whether they were closed, "
        "current score, open corrective actions, regulatory requirements and the areas flagged as "
        "highest risk.",
        {
            SUPERVISOR: "Prepares records and makes their team available.",
            ADMIN: "Flags any specific concern to include in scope.",
            SYSTEM: "Supplies context. Retrieves past findings and the regulatory guidance relevant "
                    "to this audit type, and pre-populates the checklist with the highest-risk items first.",
        },
    ),
    Step(
        4, "opening_meeting", CONDUCT, "Opening meeting", AUDITOR, False, False,
        "Presents scope, method and sampling approach. Confirms logistics with the site.",
        {
            SUPERVISOR: "Attends the opening. Scope and approach are agreed jointly, so there is no "
                        "dispute later about what was in or out of scope.",
            SYSTEM: "Records the meeting. Captures scope, attendees and the agreed approach as a "
                    "structured record.",
        },
    ),
    Step(
        5, "field_inspection", CONDUCT, "Field inspection", AUDITOR, False, True,
        "Walks the site, interviews workers and supervisors, observes actual practice, reviews "
        "records. Every observation is logged live on the app — no paper, no writing up afterwards.",
        {
            WORKER: "Interviewed directly. Asked to explain the hazards of their task, demonstrate "
                    "the procedure, and show their competence card. What the worker actually does "
                    "is the evidence — not what the procedure says.",
            SUPERVISOR: "Makes staff and areas accessible. Accompanies the auditor on the walk.",
            SAFETY_MANAGER: "Notified immediately if a critical item scores zero during the walk — "
                            "work may be suspended on the spot.",
            ADMIN: "Notified immediately of any critical finding.",
            SYSTEM: "Validates as you go. Checks mandatory items are answered and alerts instantly "
                    "if a critical item scores zero.",
        },
    ),
    Step(
        6, "evidence_captured", CONDUCT, "Evidence captured", AUDITOR, False, False,
        "Photos, documents, training records and maintenance logs, each linked to the specific "
        "checklist item it evidences.",
        {
            WORKER: "May be asked to show training records, PPE condition, or the permit covering "
                    "their work.",
            SUPERVISOR: "Provides records and documents on request.",
            SYSTEM: "Links the evidence. Ties every photo and document to its checklist item, and "
                    "checks photo quality before the audit can close.",
        },
    ),
    Step(
        7, "findings_and_score", CLASSIFY, "Findings & score", AUDITOR, False, True,
        "Classifies every finding. Scores each item and assigns the classification — the system "
        "calculates the score, but the auditor owns the judgement on what each finding is.",
        {
            SAFETY_MANAGER: "Notified within 24 hours of any Major non-conformance.",
            SYSTEM: "Calculates the score. Applies the rubric, computes section and overall "
                    "percentages, applies the non-conformance thresholds, and flags any repeat of a "
                    "finding from the last two audits.",
        },
    ),
    Step(
        8, "closing_meeting", AGREE, "Closing meeting", AUDITOR, False, True,
        "Presents findings to the supervisor and agrees corrective action timeframes.",
        {
            SUPERVISOR: "Confirms factual accuracy — their opportunity to correct a factual error "
                        "before anything is fixed. After this meeting findings are locked and can "
                        "only change through a formal amendment.",
            SAFETY_MANAGER: "Attends for serious findings.",
            SYSTEM: "Locks the findings. After the closing meeting nothing can be edited without a "
                    "formal amendment trail.",
        },
    ),
    Step(
        9, "report_issued", REPORT, "Report issued", AUDITOR, False, True,
        "Signs the report. It cannot be issued without the auditor's signature. Signing triggers "
        "distribution and creates the corrective actions.",
        {
            SUPERVISOR: "Receives the report and takes ownership of the corrective actions for "
                        "their area.",
            ADMIN: "Reviews and approves the report, then owns distribution beyond the site.",
            ADMIN: "Receives every final report. Owns distribution beyond the site.",
            SYSTEM: "Generates and distributes. Builds the report from the data — scores, findings, "
                    "benchmark against last time, standard clause mapping — and creates a corrective "
                    "action for every non-conformance automatically.",
        },
    ),
    Step(
        10, "findings_tracked_out", CLOSE, "Findings tracked out", SYSTEM, False, True,
        "Keeps the audit open until every action is verified. Confirms findings were genuinely "
        "closed, not just marked closed.",
        {
            AUDITOR: "Verifies effectiveness at 30, 60 and 90 days.",
            WORKER: "Completes any corrective action assigned to them, and receives the resulting "
                    "lesson as a toolbox talk.",
            SUPERVISOR: "Completes those actions and confirms the fix is holding in day-to-day "
                        "operation.",
            ADMIN: "Escalates critical findings, owns the re-audit decision and the cross-site trend review.",
            ADMIN: "Owns cross-site trend review and the response to repeat findings across the "
                   "organisation.",
            SYSTEM: "Tracks and triggers. Compares against previous audits and against peer sites, "
                    "and fires the re-audit trigger when the rules are met.",
        },
    ),
]

STEP_BY_NUMBER = {s.number: s for s in STEPS}
STEP_BY_KEY = {s.key: s for s in STEPS}

# Steps 4 to 8 are conducted in the field on the phone. Everything before and
# after is the web console: schedule the programme, review and distribute.
MOBILE_STEPS = (2, 3, 4, 5, 6, 7, 8)
WEB_STEPS = (1, 2, 9, 10)

DONE, ACTIVE, BLOCKED, TODO = "done", "active", "blocked", "todo"


@dataclass
class StepFacts:
    """What the caller has to establish before the steps can be read.

    Deliberately explicit rather than letting this module query: the controller
    already holds the items and findings it loaded for the response, and having
    two places issue the same queries is how the step display ends up disagreeing
    with the body it is rendered next to.
    """
    team_assigned: bool = False
    brief_pack_reviewed: bool = False
    opening_meeting_held: bool = False
    items_total: int = 0
    items_answered: int = 0
    evidence_owed: int = 0          # scoring items with no evidence attached
    classified: bool = False
    auditee_confirmed: bool = False
    findings_locked: bool = False
    report_issued: bool = False
    report_approved: bool = False
    open_findings: int = 0
    closed: bool = False
    stop_work: bool = False


def _states(f: StepFacts) -> List[str]:
    """done / blocked / active / todo for each of the ten, in order."""
    fieldwork_done = f.items_total > 0 and f.items_answered >= f.items_total
    evidence_done = fieldwork_done and f.evidence_owed == 0

    done = [
        True,                       # 01 the audit row exists because the system made it
        f.team_assigned,
        f.brief_pack_reviewed,
        f.opening_meeting_held,
        fieldwork_done,
        evidence_done,
        f.classified,
        f.auditee_confirmed and f.findings_locked,
        f.report_issued,
        f.closed,
    ]

    states = []
    first_open = None
    for i, is_done in enumerate(done):
        if is_done:
            states.append(DONE)
        else:
            states.append(TODO)
            if first_open is None:
                first_open = i

    if first_open is None:
        return states

    states[first_open] = ACTIVE

    # Hard stops — the audit cannot progress until the condition is met, which is
    # a different thing from simply being next in the sequence.
    n = first_open + 1
    if n == 5 and f.stop_work:
        states[first_open] = BLOCKED          # critical finding, contain it first
    if n == 9 and not (f.auditee_confirmed and f.findings_locked):
        states[first_open] = BLOCKED          # nothing to sign until findings lock
    if n == 10 and f.open_findings > 0:
        states[first_open] = BLOCKED          # stays open until every action is verified

    return states


def describe(facts: StepFacts) -> List[dict]:
    states = _states(facts)
    return [
        {
            "number": step.number,
            "key": step.key,
            "phase": step.phase,
            "label": step.label,
            "owner": step.owner,
            "owner_label": ROLES[step.owner]["label"],
            "automatic": step.automatic,
            "hard_stop": step.hard_stop,
            "on_mobile": step.number in MOBILE_STEPS,
            "detail": step.detail,
            "state": state,
        }
        for step, state in zip(STEPS, states)
    ]


def current(facts: StepFacts) -> Optional[Step]:
    """The step the audit is waiting on, or None once it is closed."""
    for step, state in zip(STEPS, _states(facts)):
        if state in (ACTIVE, BLOCKED):
            return step
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Status vocabulary — what the rest of the system reads
# ══════════════════════════════════════════════════════════════════════════════
#
# `status` stays the single field every existing dashboard, KPI query and web
# screen filters on, so the ten steps map back onto it rather than replacing it.
# The mapping runs step -> status, one direction only, and is applied after every
# transition so the two can never disagree.

STEP_STATUS = {
    1: "scheduled",
    2: "scheduled",
    3: "in_progress",
    4: "in_progress",
    5: "fieldwork",
    6: "fieldwork",
    7: "fieldwork",
    8: "findings_raised",
    9: "findings_raised",
    10: "pending_review",
}


def status_for(facts: StepFacts) -> str:
    """The status the audit should carry, given where it actually is."""
    if facts.closed:
        return "completed"
    if facts.stop_work:
        return "immediate_action"
    step = current(facts)
    if step is None:
        return "completed"
    if step.number == 10:
        # Step 10 splits: actions still owed is IMPROVE, everything verified but
        # not yet closed is LEARN. Collapsing both to one status was what made a
        # fully-verified audit look identical to one with six open actions.
        return "capa_open" if facts.open_findings else "verified"
    return STEP_STATUS[step.number]


def reference() -> dict:
    """The ten steps and the role map, for the app's flow screen — readable offline."""
    return {
        "steps": [
            {
                "number": s.number, "key": s.key, "phase": s.phase, "label": s.label,
                "owner": s.owner, "owner_label": ROLES[s.owner]["label"],
                "automatic": s.automatic, "hard_stop": s.hard_stop,
                "on_mobile": s.number in MOBILE_STEPS,
                "detail": s.detail,
                "role_notes": {
                    role: note for role, note in s.role_notes.items()
                },
            }
            for s in STEPS
        ],
        "roles": [{"key": k, **v} for k, v in ROLES.items()],
        "mobile_steps": list(MOBILE_STEPS),
        "web_steps": list(WEB_STEPS),
        "spec_mapping": [
            {"document_role": "Lead Auditor + Audit Team", "platform_role": AUDITOR,
             "note": "One role; where several are assigned to one audit, one is designated lead."},
            {"document_role": "Auditee Management", "platform_role": SUPERVISOR,
             "note": "The supervisor of the area under audit."},
            {"document_role": "Workers interviewed", "platform_role": WORKER,
             "note": "Observed and questioned during the walk."},
            {"document_role": "Safety Manager / Safety Advisor", "platform_role": SAFETY_MANAGER,
             "note": "Mobile only. Receives the critical and Major NC alerts; owns no step."},
            {"document_role": "ISMS Director / Safety Director", "platform_role": ADMIN,
             "note": "The web console. Owns every step conducted there — 01, 02, 09 and 10."},
        ],
    }
