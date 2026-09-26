"""The domain event bus.

Source: Architecture doc section 6 (Event Driven Platform), and the slide's
third promise — "Every Closure Improves the System."

Design, and why:

  · **Outbox, not fire-and-forget.** `publish()` writes the event in the caller's
    transaction. If the business change rolls back the event goes with it; if it
    commits the event is durable. A bus that publishes before commit will
    eventually tell four downstream systems about a closure that never happened.

  · **Dispatch after commit.** Handlers run once the caller has committed, on
    their own sessions. A handler that raises must not undo the closure that
    triggered it — closing an incident is the user's action, and the cascade is
    a consequence, not a precondition.

  · **Per-handler delivery rows.** Each subscriber succeeds or fails on its own.
    A broken training handler does not stop the inspection handler.

  · **Idempotent by construction.** The (event_id, handler) unique key means a
    replay or a duplicate publish cannot raise the same competence gap twice.

This is in-process. The spec puts it on Azure Service Bus; the seam is
`dispatch()` — swap it for a queue consumer and neither the publishers nor the
handlers change.
"""
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.domain_event import DomainEvent, EventDelivery

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3

PENDING, DELIVERED, FAILED, DEAD = "pending", "delivered", "failed", "dead"

# event_type -> [handler, …]
_SUBSCRIBERS: Dict[str, List[Callable]] = {}


class HandlerResult:
    """What a handler did. Returned so the cascade is auditable rather than
    something you infer from side effects across four tables."""

    def __init__(self, summary: str, changed: bool = True):
        self.summary = summary
        self.changed = changed


def subscribe(*event_types: str):
    """Register a handler. Its __name__ is the delivery key, so renaming a
    handler makes its past deliveries orphans — rename deliberately."""
    def decorator(fn: Callable) -> Callable:
        for et in event_types:
            _SUBSCRIBERS.setdefault(et, []).append(fn)
        return fn
    return decorator


def subscribers_for(event_type: str) -> List[Callable]:
    return list(_SUBSCRIBERS.get(event_type, []))


def registry() -> Dict[str, List[str]]:
    return {et: [h.__name__ for h in hs] for et, hs in sorted(_SUBSCRIBERS.items())}


def publish(
    db: Session,
    event_type: str,
    *,
    organisation_id: Optional[int] = None,
    subject_family: Optional[str] = None,
    subject_id: Optional[int] = None,
    payload: Optional[Dict[str, Any]] = None,
    user_id: Optional[int] = None,
    correlation_id: Optional[str] = None,
    source_service: str = "hse-api",
) -> str:
    """Record an event in the outbox. Does NOT commit and does NOT dispatch.

    The caller commits — that is the point. Returns the event_id so the caller
    can pass it to `dispatch()` afterwards.
    """
    event_id = str(uuid.uuid4())
    db.add(DomainEvent(
        event_id=event_id,
        event_type=event_type,
        organisation_id=organisation_id,
        correlation_id=correlation_id,
        source_service=source_service,
        user_id=user_id,
        subject_family=subject_family,
        subject_id=subject_id,
        payload=payload or {},
        published_at=datetime.utcnow(),
    ))

    # One delivery row per subscriber, in the same transaction. If the business
    # change rolls back, so do the intentions to notify anyone about it.
    for handler in subscribers_for(event_type):
        db.add(EventDelivery(
            event_id=event_id, event_type=event_type,
            handler=handler.__name__, status=PENDING, attempts=0,
        ))
    return event_id


def dispatch(session_factory: Callable[[], Session], event_id: str) -> List[dict]:
    """Run every pending handler for one event, each on its own session.

    Called AFTER the publisher has committed. A handler failure is recorded
    against its own delivery row and never propagates — the closure already
    happened and must not be undone by a downstream consumer.
    """
    results: List[dict] = []

    with session_factory() as meta:
        event = meta.query(DomainEvent).filter(DomainEvent.event_id == event_id).first()
        if event is None:
            logger.warning("dispatch called for unknown event %s", event_id)
            return results
        pending = (
            meta.query(EventDelivery)
            .filter(EventDelivery.event_id == event_id)
            .filter(EventDelivery.status.in_([PENDING, FAILED]))
            .all()
        )
        # Detach what the handlers need so the metadata session can close.
        payload = dict(event.payload or {})
        envelope = {
            "event_id": event.event_id, "event_type": event.event_type,
            "organisation_id": event.organisation_id, "user_id": event.user_id,
            "subject_family": event.subject_family, "subject_id": event.subject_id,
            "correlation_id": event.correlation_id,
        }
        todo = [(d.id, d.handler, d.attempts) for d in pending]

    by_name = {h.__name__: h for h in subscribers_for(envelope["event_type"])}

    for delivery_id, handler_name, attempts in todo:
        handler = by_name.get(handler_name)
        with session_factory() as db:
            delivery = db.query(EventDelivery).filter(EventDelivery.id == delivery_id).first()
            if delivery is None:
                continue

            if handler is None:
                # The handler was removed or renamed since the event was
                # published. Dead rather than retried forever.
                delivery.status = DEAD
                delivery.last_error = f"no handler registered under '{handler_name}'"
                db.commit()
                results.append({"handler": handler_name, "status": DEAD})
                continue

            delivery.attempts = (delivery.attempts or 0) + 1
            try:
                outcome = handler(db, envelope, payload)
                summary = outcome.summary if isinstance(outcome, HandlerResult) else str(outcome or "ok")
                delivery.status = DELIVERED
                delivery.outcome = summary[:255]
                delivery.delivered_at = datetime.utcnow()
                delivery.last_error = None
                db.commit()
                results.append({"handler": handler_name, "status": DELIVERED, "outcome": summary})
            except Exception as e:                       # noqa: BLE001 — isolation is the point
                db.rollback()
                # Re-fetch: the rollback detached our delivery row.
                delivery = db.query(EventDelivery).filter(EventDelivery.id == delivery_id).first()
                if delivery is not None:
                    delivery.attempts = attempts + 1
                    delivery.last_error = f"{type(e).__name__}: {e}"[:2000]
                    delivery.status = DEAD if delivery.attempts >= MAX_ATTEMPTS else FAILED
                    db.commit()
                logger.exception("event handler %s failed for %s", handler_name, event_id)
                results.append({"handler": handler_name, "status": FAILED, "error": str(e)})

    return results


def publish_and_dispatch(
    db: Session, session_factory: Callable[[], Session], event_type: str, **kwargs
) -> str:
    """Publish, commit, then dispatch.

    The commit is here on purpose: it is the boundary the outbox pattern needs.
    Callers that already manage their own transaction should call publish() and
    dispatch() separately.
    """
    event_id = publish(db, event_type, **kwargs)
    db.commit()
    dispatch(session_factory, event_id)
    return event_id
