"""Addressed notifications for the CAPA lifecycle.

One place, because the same three questions come up at every step: who is the
supervisor of this owner, who are the safety managers, and how do I write a row
that reaches exactly them. Before migration 061 there was no way to address a
notification at all, so this could not exist and every step broadcast.

Failures here are logged and swallowed. A notification that does not send must
never roll back the workflow transition that triggered it — losing the record of
an evidence submission because the mail row failed would be a far worse bug than
a missed alert.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.utils.logger import get_logger

logger = get_logger(__name__)


def notify(
    db: Session,
    *,
    org_id: Optional[int],
    employee_id: Optional[int],
    title: str,
    message: str,
    category: str,
    subject_ref: Optional[str] = None,
    type_: str = "info",
) -> None:
    """One notification, addressed to one employee.

    `employee_id=None` means org-wide, which is what every pre-061 notification
    was. Callers should pass a real id — the whole point of the escalation chain
    is that it reaches a named person.

    Written inside a savepoint and flushed here, so a row the database refuses
    rolls back only itself. `db.add` on its own issues no SQL — the INSERT
    happens at the caller's flush, long after this try block has exited — so
    catching around the add swallowed nothing and a bad notification still took
    down the workflow transition that raised it. That is the exact failure this
    function's contract promises cannot happen.
    """
    try:
        with db.begin_nested():
            db.add(Notification(
                organisation_id=org_id,
                title=title[:255],
                message=message,
                type=type_,
                target_type="all" if employee_id is None else "specific",
                target_employee_id=employee_id,
                category=category,
                subject_ref=subject_ref,
                status="sent",
                sent_at=datetime.utcnow(),
            ))
            db.flush()
    except Exception:
        logger.exception("Notification failed (category=%s ref=%s)", category, subject_ref)


def supervisor_of(db: Session, employee_id: Optional[int]) -> Optional[int]:
    """The owner's line manager, for the 90% escalation.

    Falls back to None rather than guessing: notifying an arbitrary supervisor
    about someone else's action is worse than notifying nobody, because it
    trains people to ignore the channel.
    """
    if not employee_id:
        return None
    try:
        # `manager_id` is the reporting line on employees — there is no
        # supervisor_id column.
        return db.execute(
            text("SELECT manager_id FROM employees WHERE id = :id"), {"id": employee_id}
        ).scalar()
    except Exception:
        logger.exception("Could not resolve supervisor for employee %s", employee_id)
        return None


def safety_managers(db: Session, org_id: Optional[int]) -> List[int]:
    """Employee ids of everyone who can approve a closure, for the 100% step."""
    try:
        rows = db.execute(
            text(
                "SELECT u.employee_id FROM users u "
                "JOIN app_roles ar ON ar.id = u.app_role_id "
                "WHERE u.organisation_id = :org AND u.is_active = 1 "
                "  AND u.employee_id IS NOT NULL "
                "  AND LOWER(ar.name) IN ('safety_manager', 'admin', 'superadmin')"
            ),
            {"org": org_id},
        ).scalars().all()
        return [r for r in rows if r]
    except Exception:
        logger.exception("Could not resolve safety managers for org %s", org_id)
        return []


def notify_many(db: Session, employee_ids: List[int], **kwargs) -> None:
    for emp in employee_ids:
        notify(db, employee_id=emp, **kwargs)
