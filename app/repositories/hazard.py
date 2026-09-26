from app.repositories.base import BaseRepository
from app.models.hazard import Hazard


class HazardRepository(BaseRepository[Hazard]):
    model_class = Hazard
