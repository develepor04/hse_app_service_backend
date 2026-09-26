from typing import Optional
from sqlalchemy.orm import Session
from app.repositories.hazard import HazardRepository
from app.schemas.hazard import HazardCreate, HazardUpdate
from app.core.exceptions import NotFoundError
from app.utils.logger import get_logger

logger = get_logger(__name__)


class HazardService:
    def __init__(self, db: Session) -> None:
        self._repo = HazardRepository(db)

    def list(self, skip: int = 0, limit: int = 100, org_id: Optional[int] = None):
        logger.debug("list Hazard skip=%s limit=%s org_id=%s", skip, limit, org_id)
        if org_id is not None:
            return self._repo.get_all_by_org(org_id, skip=skip, limit=limit)
        return self._repo.get_all(skip=skip, limit=limit)

    def get(self, id: int, org_id: Optional[int] = None):
        item = self._repo.get_by_id_and_org(id, org_id) if org_id is not None else self._repo.get_by_id(id)
        if item is None:
            raise NotFoundError("Hazard", id)
        return item

    def create(self, payload: HazardCreate, org_id: Optional[int] = None):
        logger.info("create Hazard org_id=%s", org_id)
        data = payload.model_dump()
        if org_id is not None:
            data["organisation_id"] = org_id
        return self._repo.create(data)

    def update(self, id: int, payload: HazardUpdate, org_id: Optional[int] = None):
        item = (
            self._repo.update_by_org(id, org_id, payload.model_dump(exclude_unset=True))
            if org_id is not None
            else self._repo.update(id, payload.model_dump(exclude_unset=True))
        )
        if item is None:
            raise NotFoundError("Hazard", id)
        logger.info("updated Hazard id=%s", id)
        return item

    def delete(self, id: int, org_id: Optional[int] = None) -> None:
        success = self._repo.delete_by_org(id, org_id) if org_id is not None else self._repo.delete(id)
        if not success:
            raise NotFoundError("Hazard", id)
        logger.info("deleted Hazard id=%s", id)
