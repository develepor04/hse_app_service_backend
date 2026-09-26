"""WF-01 Flow B · a risk assessment of a planned activity, and its ten findings.

Distinct from `RiskReport`, which is one worker's sighting of one hazard. This
is the ten-step assessment the spec makes a precondition of work starting —
see `app.services.risk_assessment` for the rules and migration 070 for why the
two tables exist.
"""
from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text
from app.models.base import Base


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)

    # 01 SCOPE
    activity = Column(String(255), nullable=False)
    task_description = Column(Text, nullable=True)
    site_id = Column(Integer, nullable=True)
    location_station_id = Column(Integer, nullable=True)

    status = Column(String(40), default="scoping", index=True)

    # 04 · the four mandatory uplifts, which describe the circumstances the work
    # happens in rather than any one hazard, so they sit on the assessment.
    uplift_no_valid_rams = Column(Integer, default=0)
    uplift_new_worker = Column(Integer, default=0)
    uplift_night_shift = Column(Integer, default=0)
    uplift_temporary_control = Column(Integer, default=0)
    uplift_total = Column(Integer, default=0)

    # 03-05 · before controls
    inherent_score = Column(Integer, nullable=True)
    adjusted_score = Column(Integer, nullable=True)
    band = Column(String(20), nullable=True)
    band_colour = Column(String(20), nullable=True)

    # 08 · after controls. This is the figure the spec hangs the decision on.
    residual_score = Column(Integer, nullable=True)
    residual_band = Column(String(20), nullable=True)
    blocks_work = Column(Integer, default=0)
    approval_route = Column(String(40), nullable=True)
    approved_by = Column(Integer, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approval_notes = Column(Text, nullable=True)

    # 09 · re-assessment
    review_frequency = Column(String(20), nullable=True)
    review_due_at = Column(DateTime, nullable=True)
    reopened_reason = Column(String(255), nullable=True)
    reopened_at = Column(DateTime, nullable=True)

    # A -> B. A hazard reported in an area this assessment covers is evidence it
    # missed something. Flagged rather than reopened: the assessment still
    # stands until somebody looks, but it can no longer be assumed sound.
    flagged_for_review = Column(Integer, default=0)
    flagged_reason = Column(String(255), nullable=True)
    flagged_at = Column(DateTime, nullable=True)
    # INCIDENT -> B. The 48-hour deadline that makes "fast-tracked" sortable.
    review_due_by = Column(DateTime, nullable=True)

    created_by = Column(Integer, nullable=True)
    archived_at = Column(DateTime, nullable=True)


class RiskAssessmentHazard(Base):
    """One of the ten categories on one assessment.

    All ten exist from the moment the assessment is created. `hazard_present`
    null means the category is still outstanding — which is what stops the
    assessment being scored, per the spec's "a category cannot be silently
    skipped".
    """

    __tablename__ = "risk_assessment_hazards"

    assessment_id = Column(Integer, ForeignKey("risk_assessments.id"), nullable=False, index=True)
    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)

    # 02
    category_key = Column(String(40), nullable=False)
    category_name = Column(String(100), nullable=False)
    category_id = Column(Integer, nullable=True)
    hazard_present = Column(String(3), nullable=True)   # Yes | No | null = unanswered
    description = Column(Text, nullable=True)

    # 03 · inherent
    likelihood = Column(String(50), nullable=True)
    severity = Column(String(50), nullable=True)
    inherent_score = Column(Integer, nullable=True)

    # 06-07 · the control and who owns it
    control_hierarchy = Column(String(40), nullable=True)
    control_description = Column(Text, nullable=True)
    control_owner_id = Column(Integer, nullable=True)
    control_due_date = Column(Date, nullable=True)

    # 08 · after the control
    residual_likelihood = Column(String(50), nullable=True)
    residual_severity = Column(String(50), nullable=True)
    residual_score = Column(Integer, nullable=True)

    # B -> A · the register entry this finding created
    hazard_id = Column(Integer, nullable=True)
