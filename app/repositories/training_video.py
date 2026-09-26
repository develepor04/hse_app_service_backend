from app.repositories.base import BaseRepository
from app.models.training_video import TrainingVideo


class TrainingVideoRepository(BaseRepository[TrainingVideo]):
    model_class = TrainingVideo
