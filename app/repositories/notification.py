from typing import List, Dict, Optional, Tuple, Set
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from app.models.notification import Notification
from app.models.notification_read import NotificationRead


def _visible_to(employee_id: Optional[int]):
    """Org-wide notifications, plus the ones addressed to this employee.

    A notification with no `target_employee_id` is org-wide — that is every row
    written before migration 061, so existing behaviour is preserved exactly.
    Anything addressed to someone else is now filtered out, which it was not
    before: a CAPA assignment naming one person went to the whole organisation.
    """
    if employee_id is None:
        return Notification.target_employee_id.is_(None)
    return or_(
        Notification.target_employee_id.is_(None),
        Notification.target_employee_id == employee_id,
    )


class NotificationRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_for_org(
        self,
        org_id: int,
        skip: int = 0,
        limit: int = 50,
        employee_id: Optional[int] = None,
    ) -> List[Notification]:
        return (
            self._db.query(Notification)
            .filter(
                Notification.status == "sent",
                Notification.organisation_id == org_id,
                _visible_to(employee_id),
            )
            .order_by(Notification.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_read_ids_for_user(self, user_id: int) -> Set[int]:
        rows = (
            self._db.query(NotificationRead.notification_id)
            .filter(NotificationRead.user_id == user_id)
            .all()
        )
        return {r.notification_id for r in rows}

    def get_unread_count(self, org_id: int, user_id: int, employee_id: Optional[int] = None) -> int:
        # Counted over the same visibility filter as the list, or the badge
        # would show unread items the user cannot open.
        total = (
            self._db.query(func.count(Notification.id))
            .filter(
                Notification.status == "sent",
                Notification.organisation_id == org_id,
                _visible_to(employee_id),
            )
            .scalar()
        ) or 0

        read = (
            self._db.query(func.count(NotificationRead.id))
            .join(Notification, Notification.id == NotificationRead.notification_id)
            .filter(
                NotificationRead.user_id == user_id,
                Notification.organisation_id == org_id,
                Notification.status == "sent",
                _visible_to(employee_id),
            )
            .scalar()
        ) or 0

        return max(0, total - read)

    def mark_read(self, notification_id: int, user_id: int) -> None:
        existing = (
            self._db.query(NotificationRead)
            .filter(
                NotificationRead.notification_id == notification_id,
                NotificationRead.user_id == user_id,
            )
            .first()
        )
        if not existing:
            record = NotificationRead(
                notification_id=notification_id,
                user_id=user_id,
                read_at=datetime.utcnow(),
            )
            self._db.add(record)
            self._db.flush()

    def mark_all_read(self, org_id: int, user_id: int) -> None:
        notifications = (
            self._db.query(Notification.id)
            .filter(
                Notification.status == "sent",
                Notification.organisation_id == org_id,
            )
            .all()
        )
        already_read = self.get_read_ids_for_user(user_id)
        for (notif_id,) in notifications:
            if notif_id not in already_read:
                self._db.add(NotificationRead(
                    notification_id=notif_id,
                    user_id=user_id,
                    read_at=datetime.utcnow(),
                ))
        self._db.flush()

    def create(self, data: dict) -> Notification:
        notif = Notification(**data)
        self._db.add(notif)
        self._db.flush()
        self._db.refresh(notif)
        return notif
