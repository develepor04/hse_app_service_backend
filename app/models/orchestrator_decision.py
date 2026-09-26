"""Immutable record of one AI Orchestrator decision.

Source: Enterprise Architecture ISMS v1.0 Section 1.2 step 8, Section 8.1.

Write-once by convention. Nothing in the application updates a row after
creation — if a human later overrides the decision, that is a new record
referencing this one, not an edit (Section 10.3).
"""
from sqlalchemy import Column, DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.mysql import JSON

from app.models.base import Base


class OrchestratorDecision(Base):
    __tablename__ = "orchestrator_decisions"

    organisation_id = Column(Integer, nullable=True, index=True)
    user_id = Column(Integer, nullable=True)
    correlation_id = Column(String(64), nullable=True)

    capability_id = Column(String(40), nullable=False)
    capability_version = Column(String(20), nullable=True)

    engine_selected = Column(String(40), nullable=True)
    engines_tried = Column(JSON, nullable=True)
    engines_skipped = Column(JSON, nullable=True)

    confidence = Column(Numeric(6, 4), nullable=True)
    threshold_applied = Column(Numeric(6, 4), nullable=True)
    pathway = Column(String(20), nullable=True)

    requires_hitl = Column(Integer, default=0)
    hitl_reason = Column(String(255), nullable=True)
    hitl_sla_minutes = Column(Integer, nullable=True)
    hitl_due_at = Column(DateTime, nullable=True)

    # SHA-256 only. The raw input is never stored here — see migration 047.
    input_hash = Column(String(64), nullable=True)
    explanation = Column(Text, nullable=True)

    latency_ms = Column(Integer, nullable=True)
    cost = Column(Numeric(10, 6), default=0)
