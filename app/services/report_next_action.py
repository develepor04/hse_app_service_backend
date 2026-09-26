"""What has to happen next on a near miss, unsafe act or risk report.

The report-family twin of `incident_next_action`. Same job, same response
shape, and — unlike the hazard register — the *same* status vocabulary: near
misses, unsafe acts and risk reports all run `ReportWorkflowMixin.workflow_status`
through `report_workflow_factory`, which is the identical state machine
incidents run.

So why a module at all rather than calling `incident_next_action` directly?
Wording. Every string in that table says "incident", and a supervisor holding a
phone that tells them to "acknowledge the incident" when they are looking at a
near miss will report an incident. The steps are shared; the nouns are not. The
table below is therefore built per family from one template, so a change to what
a stage *does* still lands on all four families at once.

The role machinery is imported from `incident_next_action` for the reason
`hazard_next_action` gives: which login role belongs to which family, and which
families may act on whose step, are not incident-specific despite the module
name, and two copies would disagree the first time a role was added.
"""
from typing import Dict, List, Optional

from app.services import workflow_stages
from app.services.incident_next_action import (
    CAPA_OWNER,
    MANAGER,
    NOBODY,
    SUPERVISOR,
    NextAction,
    _CAN_ACT,
    _is_mine,
    _normalise_role,
)

# The families that run this vocabulary. `incident` is included so a caller that
# already has a family string does not have to special-case it; incidents have
# their own controller, but the answer here is the same one it would give.
FAMILY_NOUN: Dict[str, str] = {
    "incident": "incident",
    "near_miss": "near miss",
    "unsafe_act": "unsafe act",
    "risk": "risk report",
}

DEFAULT_NOUN = "report"


def _table(noun: str, route: str) -> Dict[str, NextAction]:
    """The one outstanding step per status, worded for one family.

    Read as "what is outstanding", not "what just happened" — the same reading
    `workflow_stages.REPORT_STATUS_STAGE` uses, so a status maps to the stage
    whose work is still open.
    """
    return {
        "draft": NextAction(
            action="Submit the report",
            detail=f"This {noun} was captured but never submitted.",
            owner=NOBODY,
            route=route,
            cta="Open",
            unblocks="Stage 02 ASSESS",
        ),
        "reported": NextAction(
            action=f"Acknowledge the {noun}",
            detail=(
                f"Take control of the {noun}, confirm the area is safe and nobody "
                "is still exposed to what nearly went wrong."
            ),
            owner=SUPERVISOR,
            route=route,
            cta="Acknowledge",
            unblocks="Stage 03 RESPOND",
        ),
        "acknowledged": NextAction(
            action="Start the investigation",
            detail=(
                "Open the investigation so the response clock measures a window "
                "somebody is actually working in."
            ),
            owner=SUPERVISOR,
            route=route,
            cta="Start investigation",
            unblocks="Stage 04 INVESTIGATE",
        ),
        "under_investigation": NextAction(
            action="Submit the investigation",
            detail=(
                "Record the root cause, the 5-Why chain and the corrective action "
                "that stops it happening for real next time."
            ),
            owner=SUPERVISOR,
            route=route,
            cta="Submit to manager",
            unblocks="Stage 05 IMPROVE",
        ),
        "escalated": NextAction(
            action="Review the escalation",
            detail=f"A supervisor escalated this {noun} to you. Review the findings and decide.",
            owner=MANAGER,
            route=route,
            cta="Review now",
            unblocks="Stage 05 IMPROVE",
        ),
        "pending_approval": NextAction(
            action="Approve the investigation",
            detail="Confirm the root cause holds and the corrective action addresses it.",
            owner=MANAGER,
            route=route,
            cta="Review now",
            unblocks="Stage 05 IMPROVE",
        ),
        "capa_open": NextAction(
            action="Sign off the outstanding corrective actions",
            detail=f"The {noun} stays in IMPROVE until its last action closes — not the first.",
            owner=CAPA_OWNER,
            route=route,
            cta="Sign off now",
            unblocks="Stage 06 VERIFY",
        ),
        "pending_verification": NextAction(
            action="Verify the corrective action worked",
            detail="Confirm the fix actually held. Answering no reopens the action.",
            owner=MANAGER,
            route=route,
            cta="Verify now",
            unblocks="Stage 07 LEARN",
        ),
        # Legacy alias for pending_verification — see REPORT_STATUS_STAGE.
        "investigated": NextAction(
            action="Verify the corrective action worked",
            detail="Confirm the fix actually held. Answering no reopens the action.",
            owner=MANAGER,
            route=route,
            cta="Verify now",
            unblocks="Stage 07 LEARN",
        ),
        "approved": NextAction(
            action="Capture the lesson and close",
            detail=(
                "Closing updates the linked hazard, the training gap, the inspection "
                "schedule and the learning corpus."
            ),
            owner=MANAGER,
            route=route,
            cta=f"Close {noun}",
            unblocks="Closed",
        ),
    }


# Built once per family at import, not per request.
_TABLES: Dict[str, Dict[str, NextAction]] = {
    family: _table(noun, f"{family.replace('_', '-')}-workflow")
    for family, noun in FAMILY_NOUN.items()
}


def _table_for(family: str) -> Dict[str, NextAction]:
    return _TABLES.get((family or "").strip().lower()) or _table(
        DEFAULT_NOUN, "report-workflow"
    )


def next_action_for(family: str, workflow_status: Optional[str]) -> Optional[NextAction]:
    """The outstanding step for a status, or None when the record is closed."""
    return _table_for(family).get((workflow_status or "").strip().lower())


def describe(
    family: str,
    workflow_status: Optional[str],
    user_role: Optional[str] = None,
) -> dict:
    """Stage + next action for one record, from the viewer's perspective.

    `is_mine` is the field a queue filters on: it means "this action is this
    role's own job", not merely "this role is senior enough to do it".
    """
    stage_key = workflow_stages.stage_for(family, workflow_status)
    stage = workflow_stages.STAGE_BY_KEY.get(stage_key) if stage_key else None
    nxt = next_action_for(family, workflow_status)
    role = _normalise_role(user_role)

    if nxt is None:
        return {
            "workflow_status": workflow_status,
            "stage": stage_key,
            "stage_number": workflow_stages.stage_number(stage_key),
            "stage_label": stage.label if stage else None,
            "is_closed": stage_key == workflow_stages.CLOSE,
            "next_action": None,
            "can_act": False,
            "is_mine": False,
        }

    return {
        "workflow_status": workflow_status,
        "stage": stage_key,
        "stage_number": workflow_stages.stage_number(stage_key),
        "stage_label": stage.label if stage else None,
        "is_closed": False,
        "next_action": nxt.as_dict(),
        # May this user perform it at all?
        "can_act": role in _CAN_ACT.get(nxt.owner, set()),
        # Is it *their* step, rather than one they outrank?
        "is_mine": _is_mine(nxt.owner, role),
    }


def stage_track(family: str, workflow_status: Optional[str]) -> List[dict]:
    """The eight stages with done/current/pending, for the progress tracker.

    Returned from here rather than assembled in the client so the mobile rail,
    the web tracker and the queue all draw the same eight dots.
    """
    current = workflow_stages.stage_number(
        workflow_stages.stage_for(family, workflow_status)
    )
    track = []
    for s in workflow_stages.STAGES:
        if current is None:
            state = "pending"
        elif s.number < current:
            state = "done"
        elif s.number == current:
            # Reaching CLOSE is the completion — there is no ninth stage.
            state = "done" if s.key == workflow_stages.CLOSE else "current"
        else:
            state = "pending"
        track.append({
            "number": s.number,
            "key": s.key,
            "label": s.label,
            "short": s.key[:3],
            "state": state,
        })
    return track
