from app.repositories.base import BaseRepository
from app.models.permit_to_work import PermitToWork


class PermitToWorkRepository(BaseRepository[PermitToWork]):
    model_class = PermitToWork
