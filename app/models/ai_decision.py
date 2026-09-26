"""AI answer log with confidence scoring, and the human decision on it.

From HSE_AI_Overview_Client, step 6 "The answer is recorded": each answer is
stored with a confidence score and marked as AI-generated, then the user's
decision to accept, amend or reject it is captured — creating a full audit
trail, and the input the Continuous Learning loop trains on.

`snapshot_hash` is what makes an answer reproducible: it pins exactly which
grounded data snapshot produced it.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.models.aiisms_mixin import AiIsmsMetadataMixin
from app.models.base import Base


class AiDecisionLog(Base, AiIsmsMetadataMixin):
    __tablename__ = "ai_decision_log"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    user_role = Column(String(60), nullable=True)
    role_bucket = Column(String(30), nullable=True)

    question = Column(Text, nullable=True)
    answer = Column(Text, nullable=True)

    model_id = Column(String(120), nullable=True)
    model_version = Column(String(60), nullable=True)
    provider = Column(String(60), nullable=True)

    snapshot_hash = Column(String(64), nullable=True)
    snapshot_built_at = Column(DateTime, nullable=True)

    # accept | amend | reject — null until a human decides
    human_decision = Column(String(20), nullable=True, index=True)
    decision_reason = Column(Text, nullable=True)
    amended_answer = Column(Text, nullable=True)
    decided_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    decided_at = Column(DateTime, nullable=True)
