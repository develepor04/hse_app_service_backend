from app.repositories.base import BaseRepository
from app.models.permit_type import PermitType


class PermitTypeRepository(BaseRepository[PermitType]):
    model_class = PermitType
