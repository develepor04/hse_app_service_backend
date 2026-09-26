"""Visibility into the event bus.

Source: Architecture doc section 6.3 (Dead Letter Queue monitoring) and 13.1.

The cascade runs in the background, so without these endpoints "closing an event
updates everything" is unfalsifiable — you would have to go and read four tables
to find out whether anything happened. `/events/{id}` answers it directly.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config.database import SessionLocal, get_db
from app.core.dependencies import CurrentUser, get_current_user
from app.models.domain_event import DomainEvent, EventDelivery
from app.services import events as event_bus

router = APIRouter(prefix="/events", tags=["Event Bus"])

GOVERNANCE_ROLES = {
    "Manager", "HSE Manager", "Admin", "Superadmin", "Safety Manager",
    "Safety_Manager", "Director", "Auditor",
}


def _require_governance(role: str) -> None:
    if (role or "").strip().lower() not in {r.lower() for r in GOVERNANCE_ROLES}:
        raise HTTPException(status_code=403, detail=f"Role '{role}' may not read the event log")


@router.get("/subscriptions")
def subscriptions(current_user: CurrentUser = Depends(get_current_user)):
    """Which handlers listen to which events — the wiring, as configured."""
    return {"subscriptions": event_bus.registry()}


@router.get("")
def list_events(
    event_type: Optional[str] = Query(None),
    subject_family: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    _require_governance(current_user.role)
    q = db.query(DomainEvent).filter(DomainEvent.organisation_id == current_user.org_id)
    if event_type:
        q = q.filter(DomainEvent.event_type == event_type)
    if subject_family:
        q = q.filter(DomainEvent.subject_family == subject_family)
    rows = q.order_by(DomainEvent.id.desc()).limit(limit).all()

    ids = [r.event_id for r in rows]
    deliveries = (
        db.query(EventDelivery).filter(EventDelivery.event_id.in_(ids)).all() if ids else []
    )
    by_event = {}
    for d in deliveries:
        by_event.setdefault(d.event_id, []).append(d)

    return [
        {
            "event_id": r.event_id,
            "event_type": r.event_type,
            "subject": f"{r.subject_family}:{r.subject_id}",
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "handlers": [
                {"handler": d.handler, "status": d.status, "attempts": d.attempts,
                 "outcome": d.outcome, "error": d.last_error}
                for d in sorted(by_event.get(r.event_id, []), key=lambda x: x.handler)
            ],
        }
        for r in rows
    ]


@router.get("/dead-letter")
def dead_letter(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Deliveries that exhausted their retries. Section 6.3: a non-empty DLQ is
    an alert, not a statistic."""
    _require_governance(current_user.role)
    rows = (
        db.query(EventDelivery)
        .filter(EventDelivery.status == "dead")
        .order_by(EventDelivery.id.desc()).limit(200).all()
    )
    return {
        "count": len(rows),
        "items": [
            {"event_id": r.event_id, "event_type": r.event_type, "handler": r.handler,
             "attempts": r.attempts, "error": r.last_error}
            for r in rows
        ],
    }


@router.post("/{event_id}/replay")
def replay(
    event_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Re-run the handlers that have not yet succeeded for this event.

    Delivered handlers are skipped by `dispatch`, so a replay cannot duplicate a
    side effect that already landed.
    """
    _require_governance(current_user.role)
    event = db.query(DomainEvent).filter(DomainEvent.event_id == event_id).first()
    if not event or event.organisation_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="Event not found")

    # Dead deliveries are re-armed so a replay is meaningful after a fix.
    for d in db.query(EventDelivery).filter(
        EventDelivery.event_id == event_id, EventDelivery.status == "dead"
    ).all():
        d.status = "failed"
        d.attempts = 0
    db.commit()

    return {"event_id": event_id, "results": event_bus.dispatch(SessionLocal, event_id)}
