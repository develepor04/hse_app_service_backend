from typing import Optional
from sqlalchemy.orm import Session
from app.repositories.incident import IncidentRepository
from app.schemas.incident import IncidentCreate, IncidentUpdate
from app.core.exceptions import NotFoundError
from app.utils.logger import get_logger

logger = get_logger(__name__)


class IncidentService:
    def __init__(self, db: Session) -> None:
        self._repo = IncidentRepository(db)

    def list(self, skip: int = 0, limit: int = 100, org_id: Optional[int] = None):
        logger.debug("list Incident skip=%s limit=%s org_id=%s", skip, limit, org_id)
        if org_id is not None:
            return self._repo.get_all_by_org(org_id, skip=skip, limit=limit)
        return self._repo.get_all(skip=skip, limit=limit)

    def list_filtered(
        self, org_id: int, skip: int = 0, limit: int = 100,
        status: Optional[str] = None, incident_type: Optional[str] = None,
        severity: Optional[str] = None, source: Optional[str] = None,
        q: Optional[str] = None,
    ):
        return self._repo.get_filtered_by_org(
            org_id, skip=skip, limit=limit,
            status=status, incident_type=incident_type, severity=severity, source=source, q=q,
        )

    def count_filtered(
        self, org_id: int,
        status: Optional[str] = None, incident_type: Optional[str] = None,
        severity: Optional[str] = None, source: Optional[str] = None,
        q: Optional[str] = None,
    ) -> int:
        return self._repo.count_filtered_by_org(
            org_id, status=status, incident_type=incident_type, severity=severity, source=source, q=q,
        )

    def count(self, org_id: Optional[int] = None) -> int:
        if org_id is not None:
            return self._repo.count_by_org(org_id)
        return self._repo.count_all()

    def get(self, id: int, org_id: Optional[int] = None):
        if org_id is not None:
            item = self._repo.get_by_id_and_org(id, org_id)
        else:
            item = self._repo.get_by_id(id)
        if item is None:
            raise NotFoundError("Incident", id)
        return item

    def create(self, payload: IncidentCreate, org_id: Optional[int] = None):
        logger.info("create Incident org_id=%s", org_id)
        data = payload.model_dump()
        if org_id is not None:
            data["organisation_id"] = org_id
        return self._repo.create(data)

    def update(self, id: int, payload: IncidentUpdate, org_id: Optional[int] = None):
        if org_id is not None:
            item = self._repo.update_by_org(id, org_id, payload.model_dump(exclude_unset=True))
        else:
            item = self._repo.update(id, payload.model_dump(exclude_unset=True))
        if item is None:
            raise NotFoundError("Incident", id)
        logger.info("updated Incident id=%s", id)
        return item

    def delete(self, id: int, org_id: Optional[int] = None) -> None:
        if org_id is not None:
            success = self._repo.delete_by_org(id, org_id)
        else:
            success = self._repo.delete(id)
        if not success:
            raise NotFoundError("Incident", id)
        logger.info("deleted Incident id=%s", id)
