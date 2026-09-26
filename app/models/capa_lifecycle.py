"""Evidence, progress notes and effectiveness reviews — migration 060.

Kept out of capa_action.py so the CAPA row itself stays readable. All three hang
off capa_actions.id and none of them are written anywhere except the CAPA
workflow controller and the scheduler.
"""
from sqlalchemy import Column, DateTime, Integer, String, Text
from app.models.base import Base


class CapaEvidence(Base):
    """Step 07. One row per piece of proof.

    `validation_result` is set by the system at upload, not by a person — the
    document is explicit that the evidence check is automatic.
    """
    __tablename__ = "capa_evidence"

    organisation_id = Column(Integer, nullable=True)
    capa_id = Column(Integer, nullable=False, index=True)

    evidence_type = Column(String(40), nullable=False)
    file_url = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    # When the evidenced thing happened, which is not when it was uploaded.
    # CHECK 2 compares this against the action's created_at.
    evidence_date = Column(DateTime, nullable=True)

    uploaded_by = Column(Integer, nullable=True)
    uploaded_at = Column(DateTime, nullable=True)

    validation_result = Column(String(20), nullable=True)   # accepted | rejected
    rejection_reason = Column(String(255), nullable=True)


class CapaProgressNote(Base):
    """Step 06. "Long-running actions need interim notes."

    Also what the 75% reminder checks: a nudge is only worth sending when no
    progress has actually been recorded.
    """
    __tablename__ = "capa_progress_notes"

    organisation_id = Column(Integer, nullable=True)
    capa_id = Column(Integer, nullable=False, index=True)
    note = Column(Text, nullable=False)
    percent_complete = Column(Integer, nullable=True)
    author_id = Column(Integer, nullable=True)


class CapaEffectivenessReview(Base):
    """Step 09. Scheduled at closure, one row per 30/60/90-day point."""
    __tablename__ = "capa_effectiveness_reviews"

    organisation_id = Column(Integer, nullable=True)
    capa_id = Column(Integer, nullable=False, index=True)

    review_point = Column(Integer, nullable=False)          # 30 | 60 | 90
    due_at = Column(DateTime, nullable=False)

    result = Column(String(20), nullable=False, default="pending")
    has_recurred = Column(Integer, nullable=True)
    control_in_place = Column(Integer, nullable=True)
    root_cause_addressed = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)

    reviewed_by = Column(Integer, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    triggered_reopen = Column(Integer, nullable=False, default=0)
