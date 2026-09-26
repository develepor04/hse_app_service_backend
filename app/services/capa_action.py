from typing import Optional
from sqlalchemy.orm import Session
from app.repositories.capa_action import CapaActionRepository
from app.schemas.capa_action import CapaActionCreate, CapaActionUpdate
from app.core.exceptions import NotFoundError
from app.utils.logger import get_logger

logger = get_logger(__name__)


class CapaActionService:
    def __init__(self, db: Session) -> None:
        self._repo = CapaActionRepository(db)

    def list(self, skip: int = 0, limit: int = 100, org_id: Optional[int] = None):
        logger.debug("list CapaAction skip=%s limit=%s org_id=%s", skip, limit, org_id)
        if org_id is not None:
            return self._repo.get_all_by_org(org_id, skip=skip, limit=limit)
        return self._repo.get_all(skip=skip, limit=limit)

    def get(self, id: int, org_id: Optional[int] = None):
        item = self._repo.get_by_id_and_org(id, org_id) if org_id is not None else self._repo.get_by_id(id)
        if item is None:
            raise NotFoundError("CapaAction", id)
        return item

    def create(self, payload: CapaActionCreate, org_id: Optional[int] = None):
        logger.info("create CapaAction org_id=%s", org_id)
        data = payload.model_dump()
        if org_id is not None:
            data["organisation_id"] = org_id
        capa = self._repo.create(data)

        # Send notification
        try:
            from app.models.employee import Employee
            from app.models.notification import Notification
            from datetime import datetime

            db = self._repo._db
            emp_name = "Employee"
            if capa.responsible_person_id:
                emp = db.query(Employee).filter(Employee.id == capa.responsible_person_id).first()
                if emp:
                    emp_name = emp.full_name or f"EMP-{capa.responsible_person_id}"

            notif = Notification(
                organisation_id=org_id,
                title="New CAPA Action Assigned",
                message=f"A new corrective action (CAPA) has been assigned to {emp_name}: {capa.description}",
                type="info",
                target_type="all",
                status="sent",
                sent_at=datetime.utcnow()
            )
            db.add(notif)
            db.flush()
        except Exception as e:
            logger.error("Failed to create assignment notification: %s", e)

        return capa

    def update(self, id: int, payload: CapaActionUpdate, org_id: Optional[int] = None):
        item = (
            self._repo.update_by_org(id, org_id, payload.model_dump(exclude_unset=True))
            if org_id is not None
            else self._repo.update(id, payload.model_dump(exclude_unset=True))
        )
        if item is None:
            raise NotFoundError("CapaAction", id)
        logger.info("updated CapaAction id=%s", id)
        return item

    def delete(self, id: int, org_id: Optional[int] = None) -> None:
        success = self._repo.delete_by_org(id, org_id) if org_id is not None else self._repo.delete(id)
        if not success:
            raise NotFoundError("CapaAction", id)
        logger.info("deleted CapaAction id=%s", id)
