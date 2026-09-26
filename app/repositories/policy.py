from app.repositories.base import BaseRepository
from app.models.policy import Policy


class PolicyRepository(BaseRepository[Policy]):
    model_class = Policy
