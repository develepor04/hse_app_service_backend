from typing import List, Dict, Optional
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.repositories.notification import NotificationRepository
from app.schemas.notification import NotificationOut, NotificationCreate
from app.core.exceptions import NotFoundError
from app.utils.logger import get_logger

logger = get_logger(__name__)


class NotificationService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = NotificationRepository(db)

    def _employee_id(self, user_id: int) -> Optional[int]:
        """The employee behind this login — notifications are addressed to the
        employee, while reads are tracked against the user."""
        return self._db.execute(
            text("SELECT employee_id FROM users WHERE id = :uid"), {"uid": user_id}
        ).scalar()

    def list_for_user(self, org_id: int, user_id: int, skip: int = 0, limit: int = 50) -> List[NotificationOut]:
        emp_id = self._employee_id(user_id)
        notifications = self._repo.get_for_org(org_id, skip=skip, limit=limit, employee_id=emp_id)
        read_ids = self._repo.get_read_ids_for_user(user_id)
        result = []
        for n in notifications:
            out = NotificationOut.model_validate(n)
            out.is_read = n.id in read_ids
            result.append(out)
        return result

    def get_unread_count(self, org_id: int, user_id: int) -> int:
        return self._repo.get_unread_count(org_id, user_id, employee_id=self._employee_id(user_id))

    def mark_read(self, notification_id: int, org_id: int, user_id: int) -> None:
        notifications = self._repo.get_for_org(
            org_id, limit=1000, employee_id=self._employee_id(user_id)
        )
        ids = {n.id for n in notifications}
        if notification_id not in ids:
            raise NotFoundError("Notification", notification_id)
        self._repo.mark_read(notification_id, user_id)
        logger.info("notification %s marked read by user %s", notification_id, user_id)

    def mark_all_read(self, org_id: int, user_id: int) -> None:
        self._repo.mark_all_read(org_id, user_id)
        logger.info("all notifications marked read for user %s org %s", user_id, org_id)

    def create(self, payload: NotificationCreate, org_id: int) -> NotificationOut:
        data = payload.model_dump()
        data["organisation_id"] = org_id
        data["status"] = "sent"
        data["sent_at"] = datetime.utcnow()
        notif = self._repo.create(data)
        out = NotificationOut.model_validate(notif)
        out.is_read = False
        return out
