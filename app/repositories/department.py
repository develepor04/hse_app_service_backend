from app.repositories.base import BaseRepository
from app.models.department import Department


class DepartmentRepository(BaseRepository[Department]):
    model_class = Department
