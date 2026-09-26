"""Outbox and per-handler delivery log for the domain event bus.

See migration 050. Two tables because handlers must fail independently: one
broken consumer cannot be allowed to roll back the closure that triggered it,
nor to stop its siblings running.
"""
from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.mysql import JSON

from app.models.base import Base


class DomainEvent(Base):
    __tablename__ = "domain_events"

    event_id = Column(String(36), nullable=False, unique=True, index=True)
    event_type = Column(String(60), nullable=False, index=True)
    schema_version = Column(String(10), default="1.0")
    organisation_id = Column(Integer, nullable=True, index=True)
    correlation_id = Column(String(64), nullable=True)
    source_service = Column(String(60), nullable=True)
    user_id = Column(Integer, nullable=True)

    subject_family = Column(String(30), nullable=True)
    subject_id = Column(Integer, nullable=True)

    payload = Column(JSON, nullable=True)
    published_at = Column(DateTime, nullable=False)


class EventDelivery(Base):
    __tablename__ = "event_deliveries"

    event_id = Column(String(36), nullable=False, index=True)
    event_type = Column(String(60), nullable=False)
    handler = Column(String(80), nullable=False)

    status = Column(String(20), default="pending")   # pending|delivered|failed|dead
    attempts = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
    outcome = Column(String(255), nullable=True)
    delivered_at = Column(DateTime, nullable=True)
