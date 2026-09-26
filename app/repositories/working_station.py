from app.repositories.base import BaseRepository
from app.models.working_station import WorkingStation


class WorkingStationRepository(BaseRepository[WorkingStation]):
    model_class = WorkingStation
