from app.repositories.base import BaseRepository
from app.models.safety_walk import SafetyWalk


class SafetyWalkRepository(BaseRepository[SafetyWalk]):
    model_class = SafetyWalk
