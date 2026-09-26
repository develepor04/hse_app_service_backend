"""Audit trail for the Auditor role.

The `audit_logs` table is empty — nothing in the app writes to it — so rather than
returning an empty list, the trail is derived from the workflow timestamps that the
incident / permit / hazard flows already record. Every entry here corresponds to a
real state transition that actually happened, ordered newest first.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser

router = APIRouter(prefix="/audit-trail", tags=["Audit Trail"])


# (table, timestamp column, module label, action label, reference prefix)
_TRAIL_SOURCES = [
    ("incidents", "reported_at", "Incident", "Reported", "INC"),
    ("incidents", "acknowledged_at", "Incident", "Acknowledged by supervisor", "INC"),
    ("incidents", "investigation_completed_at", "Incident", "Investigation completed", "INC"),
    ("incidents", "approved_at", "Incident", "Investigation approved", "INC"),
    ("incidents", "closed_at", "Incident", "Closed out", "INC"),
    ("permits_to_work", "requested_at", "Permit", "Requested", "PTW"),
    ("permits_to_work", "acknowledged_at", "Permit", "Acknowledged by supervisor", "PTW"),
    ("permits_to_work", "approved_at", "Permit", "Approved", "PTW"),
    ("permits_to_work", "rejected_at", "Permit", "Rejected", "PTW"),
    ("permits_to_work", "auditor_verified_at", "Permit", "Verified by auditor", "PTW"),
    ("hazards", "logged_at", "Hazard", "Logged to register", "HZD"),
    ("hazards", "reviewed_at", "Hazard", "Reviewed", "HZD"),
    ("hazards", "auditor_verified_at", "Hazard", "Verified by auditor", "HZD"),
    ("near_misses", "reported_at", "Near Miss", "Reported", "NM"),
    ("near_misses", "closed_at", "Near Miss", "Closed out", "NM"),
]


@router.get("")
@router.get("/")
def get_audit_trail(
    module: Optional[str] = None,
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> list:
    """Combined action log across incidents, permits, hazards and near misses."""
    sources = _TRAIL_SOURCES
    if module:
        wanted = module.strip().lower()
        sources = [s for s in _TRAIL_SOURCES if s[2].lower() == wanted]

    if not sources:
        return []

    # One UNION ALL beats 15 round trips, and lets MySQL do the ordering.
    parts = []
    for table, column, label, action, prefix in sources:
        parts.append(f"""
            SELECT '{prefix}' AS ref_prefix, t.id AS record_id, '{label}' AS module,
                   '{action}' AS action, t.{column} AS occurred_at
            FROM {table} t
            WHERE t.organisation_id = :org_id AND t.{column} IS NOT NULL
        """)

    sql = " UNION ALL ".join(parts) + " ORDER BY occurred_at DESC LIMIT :limit"

    rows = db.execute(text(sql), {"org_id": current_user.org_id, "limit": limit}).mappings().all()

    return [
        {
            "reference": f"{r['ref_prefix']}-{r['record_id']}",
            "record_id": r["record_id"],
            "module": r["module"],
            "action": r["action"],
            "occurred_at": r["occurred_at"].isoformat() if r["occurred_at"] else None,
        }
        for r in rows
    ]
