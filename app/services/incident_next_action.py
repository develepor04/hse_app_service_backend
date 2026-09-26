"""What has to happen next on an incident, who owns it, and where to do it.

The manager app could already show *where* an incident sat — MgrInvestigation
renders "Stage 06 · Confirm it worked" and friends — but only once you had
opened that one incident and scrolled to the bottom. Nothing anywhere answered
"which incidents are waiting on me, and what exactly do I do?", so a manager who
approved an investigation was dropped into an Assign Actions screen with no
explanation, and the CAPA that actually unblocked the incident lived three taps
away under a drawer menu.

This module is the single answer to that question. Both the dashboard queue and
the incident screen read it, so the two can never disagree about what is owed.

**Why a table and not a rules engine.** The lifecycle is eight fixed stages with
one outstanding action each; a dict keyed by `workflow_status` is the whole
truth and can be read at a glance next to the workflow slide. `stage` is not
repeated here — it is derived from `workflow_stages.stage_for`, which stays the
one place the status→stage mapping lives.
"""
from typing import Dict, List, Optional

from app.services import workflow_stages

# Role families, matching the sets `incident_workflow` enforces on the write
# endpoints. The queue must not offer an action the controller would then
# refuse, so these are deliberately the same names.
SUPERVISOR = "supervisor"
MANAGER = "manager"
CAPA_OWNER = "capa_owner"
NOBODY = "nobody"


class NextAction:
    """One outstanding step. `route` is the mobile screen that performs it."""

    def __init__(
        self,
        action: str,
        detail: str,
        owner: str,
        route: str,
        cta: str,
        unblocks: Optional[str] = None,
    ):
        self.action = action
        self.detail = detail
        self.owner = owner
        self.route = route
        self.cta = cta
        # What moving past this step achieves, so the screen can say
        # "closing the last action moves this incident to 06 VERIFY".
        self.unblocks = unblocks

    def as_dict(self) -> dict:
        return {
            "action": self.action,
            "detail": self.detail,
            "owner_role": self.owner,
            "route": self.route,
            "cta": self.cta,
            "unblocks": self.unblocks,
        }


# workflow_status -> the one thing that is owed.
#
# Read this as "what is outstanding", not "what just happened" — the same
# reading `workflow_stages.REPORT_STATUS_STAGE` uses, so a status maps to the
# stage whose work is still open.
_NEXT: Dict[str, NextAction] = {
    "reported": NextAction(
        action="Acknowledge the incident",
        detail="Take control of the report, confirm the scene is safe and the injured person treated.",
        owner=SUPERVISOR,
        route="investigation",
        cta="Acknowledge",
        unblocks="Stage 04 INVESTIGATE",
    ),
    "acknowledged": NextAction(
        action="Start the investigation",
        detail="Open the investigation so the SLA clock measures a window somebody is actually working in.",
        owner=SUPERVISOR,
        route="investigation",
        cta="Start investigation",
        unblocks="Stage 04 INVESTIGATE",
    ),
    "under_investigation": NextAction(
        action="Submit the investigation",
        detail="Record the root cause, the 5-Why analysis and the corrective action plan.",
        owner=SUPERVISOR,
        route="investigation",
        cta="Submit to manager",
        unblocks="Stage 05 IMPROVE",
    ),
    "escalated": NextAction(
        action="Review the escalation",
        detail="A supervisor escalated this incident to you. Review the findings and decide.",
        owner=MANAGER,
        route="investigation",
        cta="Review now",
        unblocks="Stage 05 IMPROVE",
    ),
    "pending_approval": NextAction(
        action="Approve the investigation",
        detail="Confirm the root cause holds and the corrective action plan addresses it.",
        owner=MANAGER,
        route="investigation",
        cta="Review now",
        unblocks="Stage 05 IMPROVE",
    ),
    "capa_open": NextAction(
        action="Sign off the outstanding corrective actions",
        detail="The incident stays in IMPROVE until its last action closes — not the first.",
        owner=CAPA_OWNER,
        route="investigation",
        cta="Sign off now",
        unblocks="Stage 06 VERIFY",
    ),
    "pending_verification": NextAction(
        action="Verify the corrective action worked",
        detail="Confirm the fix actually held. Answering no reopens the action.",
        owner=MANAGER,
        route="investigation",
        cta="Verify now",
        unblocks="Stage 07 LEARN",
    ),
    # Legacy alias for pending_verification — see REPORT_STATUS_STAGE.
    "investigated": NextAction(
        action="Verify the corrective action worked",
        detail="Confirm the fix actually held. Answering no reopens the action.",
        owner=MANAGER,
        route="investigation",
        cta="Verify now",
        unblocks="Stage 07 LEARN",
    ),
    "approved": NextAction(
        action="Capture the lesson and close",
        detail="Closing updates the linked hazard, the training gap, the inspection schedule and the learning corpus.",
        owner=MANAGER,
        route="investigation",
        cta="Close incident",
        unblocks="Closed",
    ),
    "draft": NextAction(
        action="Submit the report",
        detail="This report was captured but never submitted.",
        owner=NOBODY,
        route="investigation",
        cta="Open",
        unblocks="Stage 02 ASSESS",
    ),
}


# Which role families may actually perform each owner's action, mirroring the
# `_require_role` sets in incident_workflow. A manager legitimately outranks a
# supervisor on every supervisor step, so manager sees those too — but they are
# reported as `owned_by_me: False`, which is what keeps the queue honest about
# whose job it really is.
_CAN_ACT: Dict[str, set] = {
    SUPERVISOR: {"supervisor", "safety_manager", "manager", "admin", "superadmin"},
    MANAGER: {"safety_manager", "manager", "admin", "superadmin"},
    CAPA_OWNER: {"supervisor", "safety_manager", "manager", "admin", "superadmin"},
    NOBODY: set(),
}

# The family a login role belongs to, for deciding whose job a step actually is.
_ROLE_FAMILY: Dict[str, str] = {
    "supervisor": SUPERVISOR,
    "site_inspector": SUPERVISOR,
    "site_engineer": SUPERVISOR,
    "safety_manager": MANAGER,
    "manager": MANAGER,
    "hse_manager": MANAGER,
    "director": MANAGER,
    "admin": MANAGER,
    "superadmin": MANAGER,
}

# Signing off a corrective action is reachable from either side in this app —
# the owner closes their own, and Compliance Sign-off is a manager tool — so
# both families count it as their own work rather than someone else's.
_CAPA_FAMILIES = {SUPERVISOR, MANAGER}


def _normalise_role(role: Optional[str]) -> str:
    return (role or "").strip().lower().replace(" ", "_")


def _is_mine(owner: str, role: str) -> bool:
    """Is this step this role's own job, rather than one they merely outrank?"""
    family = _ROLE_FAMILY.get(role)
    if family is None:
        return False
    if owner == CAPA_OWNER:
        return family in _CAPA_FAMILIES
    return family == owner


def next_action_for(workflow_status: Optional[str]) -> Optional[NextAction]:
    """The outstanding step for a status, or None when the incident is closed."""
    return _NEXT.get((workflow_status or "").strip().lower())


def describe(
    workflow_status: Optional[str],
    user_role: Optional[str] = None,
) -> dict:
    """Stage + next action for one incident, from the viewer's perspective.

    `is_mine` is the field the dashboard filters on: it means "this action is
    this role's own job", not merely "this role is senior enough to do it".
    """
    stage_key = workflow_stages.stage_for("incident", workflow_status)
    stage = workflow_stages.STAGE_BY_KEY.get(stage_key) if stage_key else None
    nxt = next_action_for(workflow_status)
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

    owner_roles = _CAN_ACT.get(nxt.owner, set())
    return {
        "workflow_status": workflow_status,
        "stage": stage_key,
        "stage_number": workflow_stages.stage_number(stage_key),
        "stage_label": stage.label if stage else None,
        "is_closed": False,
        "next_action": nxt.as_dict(),
        # May this user perform it at all?
        "can_act": role in owner_roles,
        # Is it *their* step, rather than one they outrank?
        "is_mine": _is_mine(nxt.owner, role),
    }


def stage_track(workflow_status: Optional[str]) -> List[dict]:
    """The eight stages with done/current/pending, for the progress tracker.

    Returned from here rather than assembled in the client so the mobile app,
    the web tracker and the queue all draw the same eight dots.
    """
    current = workflow_stages.stage_number(
        workflow_stages.stage_for("incident", workflow_status)
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
