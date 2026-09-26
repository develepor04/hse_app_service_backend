from app.repositories.base import BaseRepository
from app.models.organisation import Organisation


class OrganisationRepository(BaseRepository[Organisation]):
    model_class = Organisation
