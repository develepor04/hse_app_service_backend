from app.repositories.base import BaseRepository
from app.models.hazard_category import HazardCategory


class HazardCategoryRepository(BaseRepository[HazardCategory]):
    model_class = HazardCategory
