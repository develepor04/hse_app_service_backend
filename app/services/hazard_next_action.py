"""What has to happen next on a register unsafe act, who owns it, and where to do it.

The hazard-register twin of `incident_next_action`. Same job, same response
shape, different status vocabulary: the register runs on `register_status`
(open → interim_control → under_review → controls_planned →
pending_verification → controlled → closed) rather than the report families'
`workflow_status`.

Why the response shape is identical: the mobile stage rail, the web tracker and
the "needs your action" queue all render whatever they are handed. Giving
hazards a different shape would mean a second renderer for every one of them,
and the two would drift the first time a field was added.

The role machinery is imported from `incident_next_action` rather than copied.
Those tables — which login role belongs to which family, and which families may
act on whose step — are not incident-specific despite the module name, and two
copies would disagree the first time a role was added.
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

FAMILY = "hazard_register"


# register_status -> the one thing that is owed.
#
# Read as "what is outstanding", not "what just happened" — the same reading
# `workflow_stages.HAZARD_REGISTER_STATUS_STAGE` uses, so a status maps to the
# stage whose work is still open. `open` means the hazard is logged and nobody
# has triaged it yet, which is why it reads ASSESS rather than RECORD.
_NEXT: Dict[str, NextAction] = {
    "draft": NextAction(
        action="Submit the unsafe act",
        detail="This unsafe act was captured but never submitted to the register.",
        owner=NOBODY,
        route="hazard-register",
        cta="Open",
        unblocks="Stage 02 ASSESS",
    ),
    "open": NextAction(
        action="Assess the unsafe act",
        detail=(
            "Score it for severity and likelihood, and decide whether the job "
            "stops while the control is designed."
        ),
        owner=SUPERVISOR,
        route="hazard-register",
        cta="Assess",
        unblocks="Stage 03 RESPOND",
    ),
    "interim_control": NextAction(
        action="Open the control review",
        detail=(
            "A temporary measure is holding this unsafe act. Establish what the "
            "permanent control has to be before the interim one is relied on."
        ),
        owner=SUPERVISOR,
        route="hazard-register",
        cta="Start review",
        unblocks="Stage 04 INVESTIGATE",
    ),
    "under_review": NextAction(
        action="Plan the permanent control",
        detail=(
            "Specify the control and name its level in the hierarchy. PPE alone "
            "is the weakest answer and needs a reason."
        ),
        owner=SUPERVISOR,
        route="hazard-register",
        cta="Plan controls",
        unblocks="Stage 05 IMPROVE",
    ),
    "controls_planned": NextAction(
        action="Apply the control and submit it for verification",
        detail=(
            "The unsafe act stays in IMPROVE until the planned control is actually "
            "in place — not until it is written down."
        ),
        owner=CAPA_OWNER,
        route="hazard-register",
        cta="Submit for verification",
        unblocks="Stage 06 VERIFY",
    ),
    "pending_verification": NextAction(
        action="Verify the control held",
        detail=(
            "Confirm the permanent control is in place and working. Answering "
            "no returns the unsafe act to IMPROVE."
        ),
        owner=MANAGER,
        route="hazard-register",
        cta="Verify now",
        unblocks="Stage 07 LEARN",
    ),
    "controlled": NextAction(
        action="Capture the lesson and close",
        detail=(
            "Record what the register learned from this unsafe act, then close it. "
            "Closing updates the risk profile and the inspection schedule."
        ),
        owner=MANAGER,
        route="hazard-register",
        cta="Close unsafe act",
        unblocks="Closed",
    ),
}


def next_action_for(register_status: Optional[str]) -> Optional[NextAction]:
    """The outstanding step for a status, or None when the unsafe act is closed."""
    return _NEXT.get((register_status or "").strip().lower())


def describe(
    register_status: Optional[str],
    user_role: Optional[str] = None,
) -> dict:
    """Stage + next action for one unsafe act, from the viewer's perspective.

    `is_mine` means "this step is this role's own job", not merely "this role is
    senior enough to do it" — that distinction is what keeps the queue honest.
    """
    stage_key = workflow_stages.stage_for(FAMILY, register_status)
    stage = workflow_stages.STAGE_BY_KEY.get(stage_key) if stage_key else None
    nxt = next_action_for(register_status)
    role = _normalise_role(user_role)

    base = {
        "register_status": register_status,
        "stage": stage_key,
        "stage_number": workflow_stages.stage_number(stage_key),
        "stage_label": stage.label if stage else None,
        "is_closed": stage_key == workflow_stages.CLOSE,
    }

    if nxt is None:
        return {**base, "next_action": None, "can_act": False, "is_mine": False}

    owner_roles = _CAN_ACT.get(nxt.owner, set())
    return {
        **base,
        "is_closed": False,
        "next_action": nxt.as_dict(),
        "can_act": role in owner_roles,
        "is_mine": _is_mine(nxt.owner, role),
    }


def stage_track(register_status: Optional[str]) -> List[dict]:
    """The eight stages with done/current/pending, for the progress tracker.

    Assembled here rather than in the client so the mobile rail, the web tracker
    and the queue all draw the same eight dots from the same source.
    """
    current = workflow_stages.stage_number(
        workflow_stages.stage_for(FAMILY, register_status)
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
