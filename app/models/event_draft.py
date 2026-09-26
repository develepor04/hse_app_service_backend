"""Stage 01 RECORD — a captured but unsubmitted event, of any family.

Deliberately its own table rather than a `draft` status on incidents /
near_misses / permits_to_work: those are counted unconditionally by the
recurrence lookup behind the P1-P5 classification, the SPS engine, contractor
risk and the dashboards, so an unfinished form living in them would inflate the
KPIs and change the computed severity of other records. See migration 055.
"""
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, func

from app.models.base import Base


class EventDraft(Base):
    __tablename__ = "event_drafts"

    id = Column(Integer, primary_key=True, index=True)
    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    family = Column(String(20), nullable=False)
    created_by = Column(Integer, nullable=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
