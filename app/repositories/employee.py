from app.repositories.base import BaseRepository
from app.models.employee import Employee


class EmployeeRepository(BaseRepository[Employee]):
    model_class = Employee
