"""The mandatory cross-cutting metadata every AI-ISMS entity carries.

From HSE_Mobile_Architecture_v4, "DATA ADDITIONS · MANDATORY METADATA — ALL
ENTITIES". Kept as a mixin so the columns stay identical everywhere and the
Data Quality Gate (WF-07 auditor screen) can check them generically.

`last_verified_at` is what the Data Integrity & Validation screen reads: any
source more than 14 days stale is a Data Gap and costs a 10-point SPS penalty.
"""
from sqlalchemy import Column, DateTime, Integer, JSON, Numeric, String


class AiIsmsMetadataMixin:
    last_reviewed_at = Column(DateTime, nullable=True)
    last_verified_at = Column(DateTime, nullable=True)
    source_system = Column(String(60), nullable=True, default="server")
    jurisdiction = Column(String(60), nullable=True)
    confidence_score = Column(Numeric(5, 2), nullable=True)
    ai_generated = Column(Integer, nullable=False, default=0)
    override_history = Column(JSON, nullable=True)
