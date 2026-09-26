from app.repositories.base import BaseRepository
from app.models.role import Role


class RoleRepository(BaseRepository[Role]):
    model_class = Role
