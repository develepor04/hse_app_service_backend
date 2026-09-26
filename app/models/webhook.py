from sqlalchemy import Column, Integer, String, Boolean, DateTime
from app.models.base import Base


class Webhook(Base):
    __tablename__ = "webhooks"

    organisation_id = Column(Integer, nullable=True, index=True)
    url = Column(String(500), nullable=False)
    event_types = Column(String(255), default="")
    secret = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    last_triggered_at = Column(DateTime, nullable=True)
