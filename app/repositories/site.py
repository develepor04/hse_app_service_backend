from app.repositories.base import BaseRepository
from app.models.site import Site


class SiteRepository(BaseRepository[Site]):
    model_class = Site
