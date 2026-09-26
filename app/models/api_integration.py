from sqlalchemy import Column, Integer, String, Boolean, Text
from app.models.base import Base


class ApiIntegration(Base):
    __tablename__ = "api_integrations"

    organisation_id = Column(Integer, nullable=True, index=True)
    name = Column(String(255), nullable=False)
    type = Column(String(100), nullable=False)
    endpoint_url = Column(String(500), nullable=True)
    auth_type = Column(String(50), default="api_key")
    is_active = Column(Boolean, default=True)
    sync_frequency = Column(String(50), default="realtime")
    description = Column(Text, nullable=True)
    last_sync = Column(String(50), nullable=True)
