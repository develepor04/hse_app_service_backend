from app.repositories.base import BaseRepository
from app.models.training_program import TrainingProgram


class TrainingProgramRepository(BaseRepository[TrainingProgram]):
    model_class = TrainingProgram
