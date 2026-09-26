from app.repositories.base import BaseRepository
from app.models.shift_schedule import ShiftSchedule


class ShiftScheduleRepository(BaseRepository[ShiftSchedule]):
    model_class = ShiftSchedule
