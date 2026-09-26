from app.repositories.base import BaseRepository
from app.models.near_miss import NearMiss


class NearMissRepository(BaseRepository[NearMiss]):
    model_class = NearMiss
