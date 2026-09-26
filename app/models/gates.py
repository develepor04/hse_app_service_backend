"""The Integration Spine · deterministic gate engine.

Server-side at permit issuance and journey departure. Rule-based and auditable.
The AI layer may add context but never changes a verdict.

Every evaluation is logged, and every override captures reason, context and
outcome — that override capture is what the spec calls the Core Feature (D4),
because it is the signal the learning loop trains on.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text

from app.models.aiisms_mixin import AiIsmsMetadataMixin
from app.models.base import Base


class GateDecisionLog(Base, AiIsmsMetadataMixin):
    __tablename__ = "gate_decision_log"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    subject_type = Column(String(30), nullable=False)  # permit | journey
    subject_id = Column(Integer, nullable=True)
    gate_key = Column(String(40), nullable=False, index=True)
    verdict = Column(String(20), nullable=False, index=True)  # pass | amber | block
    reason = Column(Text, nullable=True)
    details = Column(JSON, nullable=True)
    subject_employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    evaluated_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    evaluated_at = Column(DateTime, nullable=True)


class OverrideLog(Base, AiIsmsMetadataMixin):
    __tablename__ = "override_log"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    gate_decision_id = Column(Integer, ForeignKey("gate_decision_log.id"), nullable=True)
    subject_type = Column(String(30), nullable=True)
    subject_id = Column(Integer, nullable=True)
    gate_key = Column(String(40), nullable=True)

    decision = Column(String(20), nullable=False)  # accept | amend | reject
    reason = Column(Text, nullable=False)
    context = Column(Text, nullable=True)
    outcome = Column(Text, nullable=True)

    original_verdict = Column(String(20), nullable=True)
    resulting_verdict = Column(String(20), nullable=True)
    overridden_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    overridden_by_role = Column(String(60), nullable=True)
    overridden_at = Column(DateTime, nullable=True)
