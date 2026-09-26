from sqlalchemy import Column, Integer, String, Boolean, DateTime
from app.models.base import Base


class ApiKey(Base):
    __tablename__ = "api_keys"

    organisation_id = Column(Integer, nullable=True, index=True)
    name = Column(String(255), nullable=False)
    key_prefix = Column(String(20), nullable=False)
    key_hash = Column(String(255), nullable=False)
    scopes = Column(String(255), default="Read")
    is_active = Column(Boolean, default=True)
    created_by = Column(String(255), nullable=True)
    last_used_at = Column(DateTime, nullable=True)
