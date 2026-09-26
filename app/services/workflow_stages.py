"""The one lifecycle every safety event runs through.

Source: HSE_Workflow_Engine_Slide.pptx — "One Workflow Engine. Every Safety
Event." The slide's claim is that hazards, near misses, incidents, permits and
audits all flow through the same eight stages:

    01 RECORD      capture in <60 sec
    02 ASSESS      triage — deterministic first, human sign-off where it counts
    03 RESPOND     contain and control
    04 INVESTIGATE find the root cause
    05 IMPROVE     CAPA by hierarchy of control
    06 VERIFY      confirm it worked
    07 LEARN       share the lesson
    08 CLOSE       update everything

Before this module each event type carried its own `workflow_status` vocabulary
and nothing named the stages at all, so "the same 8 stages" was a slide claim
with no code behind it. The stage is derived, not stored: `workflow_status`
remains the single source of truth that every existing query and dashboard
already reads, and the stage is computed from it. That keeps the two from
drifting apart, which is what a duplicated `stage` column would guarantee.

Permits and audits keep their own status vocabularies — they are genuinely
different processes — so they get their own mappings onto the same eight
stages rather than being forced onto the report status names.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional


# ══════════════════════════════════════════════════════════════════════════════
# The eight stages
# ══════════════════════════════════════════════════════════════════════════════

RECORD = "RECORD"
ASSESS = "ASSESS"
RESPOND = "RESPOND"
INVESTIGATE = "INVESTIGATE"
IMPROVE = "IMPROVE"
VERIFY = "VERIFY"
LEARN = "LEARN"
CLOSE = "CLOSE"


@dataclass(frozen=True)
class Stage:
    number: int
    key: str
    label: str
    description: str


STAGES: List[Stage] = [
    Stage(1, RECORD, "Record", "Capture the event in under 60 seconds."),
    Stage(2, ASSESS, "Assess", "Triage: classify severity and statutory duty."),
    Stage(3, RESPOND, "Respond", "Contain and control the immediate hazard."),
    Stage(4, INVESTIGATE, "Investigate", "Establish the root cause."),
    Stage(5, IMPROVE, "Improve", "Raise corrective actions by hierarchy of control."),
    Stage(6, VERIFY, "Verify", "Confirm the corrective action worked."),
    Stage(7, LEARN, "Learn", "Capture and share the lesson."),
    Stage(8, CLOSE, "Close", "Independent sign-off. Update everything downstream."),
]

STAGE_BY_KEY: Dict[str, Stage] = {s.key: s for s in STAGES}
STAGE_ORDER: Dict[str, int] = {s.key: s.number for s in STAGES}


# ══════════════════════════════════════════════════════════════════════════════
# Per-family status vocabularies mapped onto the eight stages
# ══════════════════════════════════════════════════════════════════════════════

# Incidents, near misses, unsafe acts and risk reports. These already share the
# ReportWorkflowMixin status set, so one mapping covers all four.
#
# A status names the state the record is *waiting in*, so it maps to the stage
# whose action is still outstanding. "acknowledged" means triage is done and
# containment is what is now owed, which is why it reads RESPOND rather than
# ASSESS. Read the mapping as "what has to happen next", not "what just
# happened", or the whole thing looks off by one.
# RECORD is held by a row in `event_drafts`, not by a status here — see
# migration 055. Writing unsubmitted drafts into `incidents` / `near_misses`
# would put them in front of the recurrence lookup, the SPS engine, contractor
# risk and every dashboard, all of which count those tables unconditionally.
# `draft` is listed so a draft can be described through the same call.
REPORT_STATUS_STAGE: Dict[str, str] = {
    "draft": RECORD,                 # captured in event_drafts, not yet submitted
    "reported": ASSESS,              # recorded — awaiting human triage of the AI's P1-P5
    "acknowledged": RESPOND,         # supervisor has taken control
    "under_investigation": INVESTIGATE,
    "escalated": INVESTIGATE,        # still being investigated, one level up
    # Approving an RCA is the tail of the investigation, not proof the fix
    # worked. Verification is its own stage now and happens after the CAPA
    # closes, per the workflow slide's 05 -> 06 order.
    "pending_approval": INVESTIGATE,
    "capa_open": IMPROVE,            # corrective actions outstanding
    "pending_verification": VERIFY,  # CAPA done, effectiveness unconfirmed
    "investigated": VERIFY,          # legacy alias for pending_verification
    "approved": LEARN,               # confirmed effective, lesson owed before closure
    "closed": CLOSE,
}

# Permit-to-work, read from `permits_to_work.workflow_status`.
#
# NOT from `status`: that column is the website's business state
# (Pending → Active → Rejected → Closed) and six analytics aggregates count
# `status == 'Active'` to mean "live permit". Driving the stage from it would
# have meant re-pointing all of those, and any miss would silently zero a
# dashboard. `workflow_status` is the permit's own state machine, read outside
# this controller only by gate_engine (which already expects `active`) and one
# `requested` count in stubs.py, so it can carry the full lifecycle safely.
PERMIT_STATUS_STAGE: Dict[str, str] = {
    "draft": RECORD,
    "requested": ASSESS,             # awaiting supervisor pickup / manager decision
    "acknowledged": ASSESS,
    "submitted": ASSESS,
    "pending": ASSESS,
    "pending_approval": ASSESS,
    "gate_check": ASSESS,
    "gate_blocked": RESPOND,         # a failed gate is a control problem to fix
    # Stage 04 for a permit: work has stopped because something went wrong under
    # it, and the cause is established before anyone goes back in. This is the
    # one genuine "investigate" state a permit has — the gate evaluation before
    # issue is triage (02), not investigation.
    "suspended": INVESTIGATE,
    "approved": IMPROVE,             # granted; controls attached before issue
    "issued": IMPROVE,
    # A permit being worked under is still stage 05: the controls are in force
    # and being relied on, but nobody has confirmed they are actually holding.
    # `active` used to map to VERIFY, which meant every live permit on site read
    # as "verified" — 3,216 of them in this database — while /verify wrote the
    # auditor's result and left workflow_status alone, so a checked permit and an
    # unchecked one were indistinguishable. VERIFY is now reached only by the
    # auditor's on-site check actually passing.
    "active": IMPROVE,
    "verified": VERIFY,              # auditor confirmed the controls on site
    # Work finished, permit spent, lesson owed before close-out. This is what
    # /complete-work writes, and until migration 067 it was written as `expired`
    # — the same word this table then had to map for the entirely different case
    # below. See that migration for why the two were separated.
    "work_complete": LEARN,
    # The validity window closed while the permit was still live. Not stage 07:
    # nothing has been completed and there is no lesson owed yet. What is owed is
    # containment — confirm nobody is still working under a lapsed authorisation,
    # then close it out — which is stage 03 for the same reason `gate_blocked` is.
    # Moving backwards from 05 is intended; `suspended` already does it.
    "expired": RESPOND,
    "closed": CLOSE,
    "cancelled": CLOSE,
    "rejected": CLOSE,               # terminal — the work never proceeded
}

# A permit that authorises work right now. Defined here, next to the mapping it
# has to agree with, because it is read by both permit_workflow and gate_engine
# and the two had already drifted: both filtered on `approved`, a status no
# endpoint writes, so the manager's monitoring list and the auditor's queue were
# permanently empty and the SIMOPS clash check ignored every issued permit.
PERMIT_LIVE_STATUSES = ("issued", "active", "verified")

# Audits and inspections. Findings are the investigation, CAPAs the improvement.
AUDIT_STATUS_STAGE: Dict[str, str] = {
    "draft": RECORD,
    "scheduled": RECORD,
    "planned": RECORD,
    "in_progress": ASSESS,
    # Stage 03 for an audit: a checklist item flagged as imminent danger stops
    # the job. Containment happens before the audit carries on, which is exactly
    # what RESPOND means everywhere else.
    "immediate_action": RESPOND,
    "fieldwork": INVESTIGATE,
    "findings_raised": IMPROVE,
    "capa_open": IMPROVE,
    "pending_review": VERIFY,
    "verified": LEARN,
    "completed": CLOSE,
    "closed": CLOSE,
}

# The standing hazard register (`hazards` table, register_status column).
#
# Distinct from the `hazard` family below, which is the worker-reported hazard
# on `risk_reports` and follows the report vocabulary. These were previously
# both pointed at REPORT_STATUS_STAGE, so every register entry resolved to no
# stage at all — none of open/under_review/controlled are report statuses.
HAZARD_REGISTER_STATUS_STAGE: Dict[str, str] = {
    "draft": RECORD,
    "open": ASSESS,                  # logged — awaiting review
    # A temporary control put in place while the permanent one is designed.
    "interim_control": RESPOND,
    "under_review": INVESTIGATE,
    "controls_planned": IMPROVE,
    "pending_verification": VERIFY,
    "controlled": LEARN,             # permanent control confirmed; lesson owed
    "closed": CLOSE,
}

# event family -> mapping
FAMILY_MAPPINGS: Dict[str, Dict[str, str]] = {
    "incident": REPORT_STATUS_STAGE,
    "near_miss": REPORT_STATUS_STAGE,
    "unsafe_act": REPORT_STATUS_STAGE,
    # `risk` is the canonical name for a worker's field observation on
    # `risk_reports`, and the one every reference stem, CAPA `subject_family`
    # and trail route uses. `hazard` is kept as an alias only because older
    # callers pass it — see event_assessment.ASSESSORS and
    # events.catalogue.CLOSURE_EVENT_FOR, which alias it the same way. Do not
    # introduce new callers on it: the standing register is `hazard_register`,
    # and a bare "hazard" reads as that to everyone looking at the console.
    "risk": REPORT_STATUS_STAGE,
    "hazard": REPORT_STATUS_STAGE,
    "hazard_register": HAZARD_REGISTER_STATUS_STAGE,
    "permit": PERMIT_STATUS_STAGE,
    "audit": AUDIT_STATUS_STAGE,
    "inspection": AUDIT_STATUS_STAGE,
}

# The five families the slide names. Kept explicit so a dashboard can render
# them in a fixed order rather than whatever the dict yields. The slide's
# "hazards" is the standing register, which is why `hazard_register` sits here
# rather than the observation family — the two are separate tables and the
# console shows them on separate screens.
EVENT_FAMILIES = ("hazard_register", "near_miss", "incident", "permit", "audit")


def stage_for(event_family: str, workflow_status: Optional[str]) -> Optional[str]:
    """Which of the eight stages is this record currently in?

    Returns None for an unknown status rather than guessing — a record whose
    status is not in the vocabulary is a data problem worth surfacing, not
    something to silently file under RECORD.
    """
    mapping = FAMILY_MAPPINGS.get((event_family or "").strip().lower())
    if mapping is None:
        return None
    return mapping.get((workflow_status or "").strip().lower())


def stage_number(stage_key: Optional[str]) -> Optional[int]:
    return STAGE_ORDER.get(stage_key) if stage_key else None


def describe(event_family: str, workflow_status: Optional[str]) -> dict:
    """Stage descriptor for an API response.

    `completed_stages` is what a progress bar needs: every stage strictly before
    the current one. It is derived from the stage number, not tracked
    separately, so it cannot disagree with the record's actual status.
    """
    key = stage_for(event_family, workflow_status)
    num = stage_number(key)
    stage = STAGE_BY_KEY.get(key) if key else None
    return {
        "event_family": event_family,
        "workflow_status": workflow_status,
        "stage": key,
        "stage_number": num,
        "stage_label": stage.label if stage else None,
        "stage_description": stage.description if stage else None,
        "total_stages": len(STAGES),
        "completed_stages": [s.key for s in STAGES if num and s.number < num],
        "is_closed": key == CLOSE,
    }


def catalogue() -> List[dict]:
    """The eight stages, for a client that wants to render the whole lifecycle."""
    return [
        {"number": s.number, "key": s.key, "label": s.label, "description": s.description}
        for s in STAGES
    ]
