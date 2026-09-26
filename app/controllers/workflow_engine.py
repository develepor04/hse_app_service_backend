"""One view of the workflow engine across every event family.

Source: HSE_Workflow_Engine_Slide.pptx — "One Workflow Engine. Every Safety
Event. Hazards, near misses, incidents, permits and audits all flow through the
same 8 stages."

These endpoints exist to make that claim checkable. Until now each family had
its own routes and its own status vocabulary, so nothing could answer "how many
events are sitting at INVESTIGATE right now" without five queries and a mental
translation table.

Nothing here writes. It reads the five families, maps each one's status onto the
shared stage vocabulary, and reports the result.
"""
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.services import workflow_stages

router = APIRouter(prefix="/workflow", tags=["Workflow Engine"])


# family -> (table, priority column or None, status column)
#
# The status column is not uniform: audits use `status`, permits keep their real
# lifecycle in `workflow_status` (their `status` column is the website's business
# state, which the analytics count), and the four report families use
# `workflow_status`. Hardcoding one name is what broke this endpoint the first
# time.
_SOURCES: Dict[str, tuple] = {
    "incident": ("incidents", "severity_priority", "workflow_status"),
    "near_miss": ("near_misses", "assessed_priority", "workflow_status"),
    "unsafe_act": ("unsafe_acts", "assessed_priority", "workflow_status"),
    # `risk`, not `hazard`. Both names map to the same stage table so the stages
    # were right either way, but the family name is also the reference stem and
    # the CAPA `subject_family`: as "hazard" this table's rows came out of
    # /workflow/queue as HAZ-12 while /risk-trail, the mobile queue and the
    # closure event all called the same record RIS-12 — and HAZ is the standing
    # register's own stem, one line below. Two families answering to one
    # reference is how an admin ends up chasing the wrong record.
    "risk": ("risk_reports", "assessed_priority", "workflow_status"),
    # The standing register is a different thing from the worker-reported risk
    # above: its own table, its own status column, its own mapping.
    "hazard_register": ("hazards", None, "register_status"),
    # workflow_status, not status: `status` is the website's business state and
    # is counted as 'Active' by the analytics dashboards, so the lifecycle rides
    # on workflow_status instead. See PERMIT_STATUS_STAGE.
    "permit": ("permits_to_work", None, "workflow_status"),
    "audit": ("audits", None, "status"),
}


@router.get("/stages")
def list_stages(current_user: CurrentUser = Depends(get_current_user)):
    """The eight stages, in order. The lifecycle definition itself."""
    return {
        "stages": workflow_stages.catalogue(),
        "event_families": list(_SOURCES.keys()),
    }


@router.get("/pipeline")
def pipeline(
    family: Optional[str] = Query(None, description="Limit to one event family"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """How many events of each family sit at each of the eight stages.

    This is the slide's headline claim rendered as data: one grid, every event
    type, the same eight columns. A family whose status is not in its mapping is
    counted under `unmapped` rather than being silently dropped — an unknown
    status is a data problem worth seeing.
    """
    families = [family] if family else list(_SOURCES.keys())
    grid: Dict[str, Dict[str, int]] = {}
    unmapped: Dict[str, Dict[str, int]] = {}

    for fam in families:
        source = _SOURCES.get(fam)
        if not source:
            continue
        table, _, status_col = source
        counts = {s.key: 0 for s in workflow_stages.STAGES}
        rows = db.execute(
            text(
                f"SELECT {status_col} AS workflow_status, COUNT(*) AS n FROM {table} "
                f" WHERE organisation_id = :org GROUP BY {status_col}"
            ),
            {"org": current_user.org_id},
        ).mappings().all()

        for r in rows:
            stage = workflow_stages.stage_for(fam, r["workflow_status"])
            if stage:
                counts[stage] += r["n"]
            else:
                unmapped.setdefault(fam, {})[r["workflow_status"] or "(null)"] = r["n"]
        grid[fam] = counts

    totals = {s.key: sum(g.get(s.key, 0) for g in grid.values()) for s in workflow_stages.STAGES}
    return {
        "stages": [s.key for s in workflow_stages.STAGES],
        "by_family": grid,
        "totals": totals,
        "unmapped_statuses": unmapped,
    }


@router.get("/queue")
def unified_queue(
    stage: Optional[str] = Query(None, description="RECORD..CLOSE"),
    overdue_only: bool = Query(False),
    limit: int = Query(100, le=300),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Every open safety event, from every family, on one priority-ranked list.

    The point of a shared assessment scale: a near miss assessed P2 outranks an
    incident assessed P4, and both appear in the same queue. Before stage 02 was
    generalised this list could not exist — only incidents carried a priority.

    Permits and audits are excluded: they have no assessed priority, so they
    cannot be ranked on the same scale. They appear in /pipeline by stage.
    """
    out: List[dict] = []

    for fam, (table, prio_col, status_col) in _SOURCES.items():
        if not prio_col:
            continue
        due_col = "investigation_due_at" if fam == "incident" else "response_due_at"
        rows = db.execute(
            text(
                f"SELECT id, {status_col} AS workflow_status, description, {prio_col} AS priority, "
                f"       {due_col} AS due_at, is_hipo, is_recurring_pattern "
                f"  FROM {table} "
                f"  WHERE organisation_id = :org AND {status_col} NOT IN ('closed','Closed') "
                f" ORDER BY {prio_col} IS NULL, {prio_col}, {due_col} "
                "  LIMIT :lim"
            ),
            {"org": current_user.org_id, "lim": limit},
        ).mappings().all()

        for r in rows:
            stage_key = workflow_stages.stage_for(fam, r["workflow_status"])
            if stage and stage_key != stage.strip().upper():
                continue
            out.append({
                "family": fam,
                "id": r["id"],
                "reference": f"{fam.upper()[:3]}-{r['id']}",
                "description": (r["description"] or "")[:140],
                "priority": r["priority"],
                "due_at": r["due_at"].isoformat() if r["due_at"] else None,
                "is_hipo": bool(r["is_hipo"]),
                "is_recurring": bool(r["is_recurring_pattern"]),
                "workflow_status": r["workflow_status"],
                "stage": stage_key,
                "stage_number": workflow_stages.stage_number(stage_key),
            })

    # P1 first, then earliest deadline. Unassessed records sort last — they are
    # not "low priority", they are "not yet triaged", and burying them at the
    # top would be worse than showing them at the bottom flagged as such.
    out.sort(key=lambda r: (r["priority"] is None, r["priority"] or "", r["due_at"] or "9999"))

    if overdue_only:
        from datetime import datetime
        now = datetime.utcnow().isoformat()
        out = [r for r in out if r["due_at"] and r["due_at"] < now]

    return {"count": len(out), "items": out[:limit]}
