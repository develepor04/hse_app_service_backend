import json
from typing import Optional, List
from sqlalchemy.orm import Session
from app.repositories.training_video import TrainingVideoRepository
from app.schemas.training_video import TrainingVideoCreate, TrainingVideoUpdate, TrainingVideoResponse
from app.models.training_video import TrainingVideo
from app.core.exceptions import NotFoundError
from app.utils.logger import get_logger

logger = get_logger(__name__)


class TrainingVideoService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = TrainingVideoRepository(db)

    @staticmethod
    def to_response(obj: TrainingVideo) -> TrainingVideoResponse:
        return TrainingVideoResponse(
            id=obj.id,
            title=obj.title,
            description=obj.description,
            video_url=obj.video_url,
            target_roles=json.loads(obj.target_roles) if obj.target_roles else [],
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )

    def list(self, org_id: Optional[int] = None, skip: int = 0, limit: int = 100) -> List[TrainingVideoResponse]:
        rows = self._repo.get_all_by_org(org_id, skip=skip, limit=limit) if org_id is not None else self._repo.get_all(skip=skip, limit=limit)
        return [self.to_response(r) for r in rows]

    def list_for_role(self, role_bucket: str, org_id: Optional[int]) -> List[TrainingVideoResponse]:
        rows = self._repo.get_all_by_org(org_id, skip=0, limit=1000) if org_id is not None else self._repo.get_all(skip=0, limit=1000)
        return [
            self.to_response(r)
            for r in rows
            if role_bucket in (json.loads(r.target_roles) if r.target_roles else [])
        ]

    def get(self, id: int, org_id: Optional[int] = None) -> TrainingVideoResponse:
        item = self._repo.get_by_id_and_org(id, org_id) if org_id is not None else self._repo.get_by_id(id)
        if item is None:
            raise NotFoundError("TrainingVideo", id)
        return self.to_response(item)

    def create(self, payload: TrainingVideoCreate, org_id: Optional[int], created_by: Optional[int]) -> TrainingVideoResponse:
        data = payload.model_dump()
        data["target_roles"] = json.dumps(data["target_roles"])
        data["organisation_id"] = org_id
        data["created_by"] = created_by
        obj = self._repo.create(data)
        logger.info("created TrainingVideo id=%s org_id=%s", obj.id, org_id)
        return self.to_response(obj)

    def update(self, id: int, payload: TrainingVideoUpdate, org_id: Optional[int] = None) -> TrainingVideoResponse:
        data = payload.model_dump(exclude_unset=True)
        if "target_roles" in data:
            data["target_roles"] = json.dumps(data["target_roles"])
        item = (
            self._repo.update_by_org(id, org_id, data)
            if org_id is not None
            else self._repo.update(id, data)
        )
        if item is None:
            raise NotFoundError("TrainingVideo", id)
        logger.info("updated TrainingVideo id=%s", id)
        return self.to_response(item)

    def delete(self, id: int, org_id: Optional[int] = None) -> None:
        success = self._repo.delete_by_org(id, org_id) if org_id is not None else self._repo.delete(id)
        if not success:
            raise NotFoundError("TrainingVideo", id)
        logger.info("deleted TrainingVideo id=%s", id)
