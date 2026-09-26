from sqlalchemy.orm import Session
from app.repositories.organisation import OrganisationRepository
from app.schemas.organisation import OrganisationCreate, OrganisationUpdate
from app.core.exceptions import NotFoundError
from app.utils.logger import get_logger

logger = get_logger(__name__)


class OrganisationService:
    def __init__(self, db: Session) -> None:
        self._repo = OrganisationRepository(db)

    def list(self, skip: int = 0, limit: int = 100):
        logger.debug("list Organisation skip=%s limit=%s", skip, limit)
        return self._repo.get_all(skip=skip, limit=limit)

    def get(self, id: int):
        item = self._repo.get_by_id(id)
        if item is None:
            raise NotFoundError("Organisation", id)
        return item

    def create(self, payload: OrganisationCreate):
        logger.info("create Organisation")
        return self._repo.create(payload.model_dump())

    def update(self, id: int, payload: OrganisationUpdate):
        item = self._repo.update(id, payload.model_dump(exclude_unset=True))
        if item is None:
            raise NotFoundError("Organisation", id)
        logger.info("updated Organisation id=%s", id)
        return item

    def delete(self, id: int) -> None:
        if not self._repo.delete(id):
            raise NotFoundError("Organisation", id)
        logger.info("deleted Organisation id=%s", id)
