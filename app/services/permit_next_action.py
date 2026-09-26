"""What has to happen next on a permit to work, who owns it, and where to do it.

The permit-to-work twin of `incident_next_action` and `hazard_next_action`.
Same job, same response shape, different status vocabulary: a permit runs on
`permits_to_work.workflow_status` (requested → acknowledged → issued → active →
expired → closed, with suspend/resume and reject as branches) rather than the
report families' state machine.

Why the response shape is identical: the mobile stage rail, the web tracker and
the "needs your action" queue all render whatever they are handed. Giving
permits a different shape would mean a second renderer for each of them.

**One difference from the incident flow that is deliberate.** The auditor is a
real participant here, not a post-closure observer. `/permit-workflow/verify` is
an on-site check performed while the permit is live and it moves the permit to
`verified` — the endpoints file states the chain as "Worker raises → Supervisor
acknowledges → Manager approves / rejects & monitors → Auditor verifies on
site". Compare `incident_next_action`, where the auditor owns nothing because
their check happens after closure and gates nothing. So this module adds an
AUDITOR owner family that the others have no use for.

The role machinery is imported from `incident_next_action` rather than copied,
for the reason that module gives: those tables are not incident-specific despite
the name, and two copies would disagree the first time a role was added. The
auditor family is layered on top here rather than pushed down into them, because
it is true of permits and false of every other family.
"""
from typing import Dict, List, Optional

from app.services import workflow_stages
from app.services.incident_next_action import (
    MANAGER,
    NOBODY,
    SUPERVISOR,
    NextAction,
    _CAN_ACT,
    _ROLE_FAMILY,
    _normalise_role,
)

FAMILY = "permit"

AUDITOR = "auditor"

# The permit chain's own owner map: the shared families, plus the auditor.
_PERMIT_CAN_ACT: Dict[str, set] = {
    **_CAN_ACT,
    AUDITOR: {"auditor", "safety_manager", "manager", "admin", "superadmin"},
}

_PERMIT_ROLE_FAMILY: Dict[str, str] = {**_ROLE_FAMILY, "auditor": AUDITOR}


def _is_mine(owner: str, role: str) -> bool:
    """Is this step this role's own job, rather than one they merely outrank?"""
    return _PERMIT_ROLE_FAMILY.get(role) == owner


# workflow_status -> the one thing that is owed.
#
# Read as "what is outstanding", not "what just happened" — the same reading
# `workflow_stages.PERMIT_STATUS_STAGE` uses, so a status maps to the stage whose
# work is still open.
_NEXT: Dict[str, NextAction] = {
    "draft": NextAction(
        action="Submit the permit request",
        detail="This permit was drafted but never submitted for approval.",
        owner=NOBODY,
        route="permit-workflow",
        cta="Open",
        unblocks="Stage 02 ASSESS",
    ),
    "requested": NextAction(
        action="Acknowledge the permit request",
        detail="Pick the request up, confirm the scope and who is doing the work.",
        owner=SUPERVISOR,
        route="permit-workflow",
        cta="Acknowledge",
        unblocks="Manager approval",
    ),
    "acknowledged": NextAction(
        action="Approve or reject the permit",
        detail="Check the controls and the gate conditions before work is authorised.",
        owner=MANAGER,
        route="permit-workflow",
        cta="Review now",
        unblocks="Stage 05 IMPROVE — the permit is issued",
    ),
    "submitted": NextAction(
        action="Approve or reject the permit",
        detail="Check the controls and the gate conditions before work is authorised.",
        owner=MANAGER,
        route="permit-workflow",
        cta="Review now",
        unblocks="Stage 05 IMPROVE — the permit is issued",
    ),
    "pending": NextAction(
        action="Approve or reject the permit",
        detail="Check the controls and the gate conditions before work is authorised.",
        owner=MANAGER,
        route="permit-workflow",
        cta="Review now",
        unblocks="Stage 05 IMPROVE — the permit is issued",
    ),
    "pending_approval": NextAction(
        action="Approve or reject the permit",
        detail="Check the controls and the gate conditions before work is authorised.",
        owner=MANAGER,
        route="permit-workflow",
        cta="Review now",
        unblocks="Stage 05 IMPROVE — the permit is issued",
    ),
    "gate_check": NextAction(
        action="Complete the gate check",
        detail="The pre-issue gate has not returned a verdict yet.",
        owner=MANAGER,
        route="permit-workflow",
        cta="Review now",
        unblocks="Stage 05 IMPROVE — the permit is issued",
    ),
    # ── 03 RESPOND ────────────────────────────────────────────────────────────
    "gate_blocked": NextAction(
        action="Clear the blocking gate condition",
        detail=(
            "A gate refused this permit. Fix what it flagged — an expired "
            "competency, a clashing permit, a missing isolation — then approve again."
        ),
        owner=SUPERVISOR,
        route="permit-workflow",
        cta="Resolve",
        unblocks="Stage 05 IMPROVE — the permit is issued",
    ),
    # ── 04 INVESTIGATE ────────────────────────────────────────────────────────
    "suspended": NextAction(
        action="Establish why work stopped, then resume or close",
        detail="Work is halted under this permit. It restarts only once the cause is understood.",
        owner=SUPERVISOR,
        route="permit-workflow",
        cta="Resume work",
        unblocks="Stage 05 IMPROVE — work restarts",
    ),
    # ── 05 IMPROVE ────────────────────────────────────────────────────────────
    "approved": NextAction(
        action="Activate the permit when work starts",
        detail="Granted with its controls attached. Activating records that work is under way.",
        owner=SUPERVISOR,
        route="permit-workflow",
        cta="Activate",
        unblocks="Stage 06 VERIFY — the controls get checked on site",
    ),
    "issued": NextAction(
        action="Activate the permit when work starts",
        detail="Issued with its controls attached. Activating records that work is under way.",
        owner=SUPERVISOR,
        route="permit-workflow",
        cta="Activate",
        unblocks="Stage 06 VERIFY — the controls get checked on site",
    ),
    "active": NextAction(
        action="Verify the controls on site",
        detail=(
            "Work is under way and the controls are being relied on, but nobody has "
            "confirmed they are actually in place. Verify, or complete the work if it is done."
        ),
        owner=AUDITOR,
        route="permit-workflow",
        cta="Verify on site",
        unblocks="Stage 06 VERIFY",
    ),
    # ── 06 VERIFY ─────────────────────────────────────────────────────────────
    "verified": NextAction(
        action="Complete the work and close the permit",
        detail="Controls were confirmed on site. Close the permit once the job is finished.",
        owner=SUPERVISOR,
        route="permit-workflow",
        cta="Complete work",
        unblocks="Stage 07 LEARN",
    ),
    # ── 03 RESPOND · the window closed while the permit was still live ────────
    # Not a lesson yet. Nothing was completed, and the outstanding step is to
    # make sure nobody is still working under an authorisation that has lapsed.
    # Only reachable once the expiry sweep writes workflow_status — see
    # migration 067 and the note in scheduler.py.
    "expired": NextAction(
        action="Confirm work has stopped, then close the permit",
        detail=(
            "The validity window closed while this permit was still live. Check nobody is "
            "working under it, then close it out. New work needs a new permit."
        ),
        owner=SUPERVISOR,
        route="permit-workflow",
        cta="Close permit",
        unblocks="Closed",
    ),
    # ── 07 LEARN ──────────────────────────────────────────────────────────────
    "work_complete": NextAction(
        action="Capture the lesson and close the permit",
        detail="The work is finished and the permit is spent. Closing records what it taught.",
        owner=SUPERVISOR,
        route="permit-workflow",
        cta="Close permit",
        unblocks="Closed",
    ),
}


def next_action_for(workflow_status: Optional[str]) -> Optional[NextAction]:
    """The outstanding step for a status, or None when the permit is finished.

    `closed`, `cancelled` and `rejected` are all terminal and deliberately
    absent: a rejected permit owes nothing, the work simply never happened.
    """
    return _NEXT.get((workflow_status or "").strip().lower())


def describe(workflow_status: Optional[str], user_role: Optional[str] = None) -> dict:
    """Stage + next action for one permit, from the viewer's perspective."""
    stage_key = workflow_stages.stage_for(FAMILY, workflow_status)
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

    return {
        "workflow_status": workflow_status,
        "stage": stage_key,
        "stage_number": workflow_stages.stage_number(stage_key),
        "stage_label": stage.label if stage else None,
        "is_closed": False,
        "next_action": nxt.as_dict(),
        "can_act": role in _PERMIT_CAN_ACT.get(nxt.owner, set()),
        "is_mine": _is_mine(nxt.owner, role),
    }


def stage_track(workflow_status: Optional[str]) -> List[dict]:
    """The eight stages with done/current/pending, for the progress tracker."""
    current = workflow_stages.stage_number(
        workflow_stages.stage_for(FAMILY, workflow_status)
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
