from app.repositories.base import BaseRepository
from app.models.capa_action import CapaAction


class CapaActionRepository(BaseRepository[CapaAction]):
    model_class = CapaAction
