from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text
from app.models.base import Base
from app.models.report_workflow_mixin import ReportWorkflowMixin


class RiskReport(Base, ReportWorkflowMixin):
    """A worker-raised risk / unsafe condition.

    Distinct from the `hazards` table, which is an organisation-wide hazard *catalog*
    (hazard_name, category, probability) that the website reads. A risk report is one
    worker's field observation and optionally points at a catalog hazard via hazard_id.
    """

    __tablename__ = "risk_reports"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    report_date = Column(Date)
    observed_date_time = Column(DateTime)
    location_station_id = Column(Integer, ForeignKey("working_stations.id"), nullable=True)
    # Added by migration 068 and never mapped, so nothing could read or write
    # them. The risk form's free-text location had nowhere to land as a result.
    location_other = Column(String(255), nullable=True)

    hazard_id = Column(Integer, ForeignKey("hazards.id"), nullable=True)
    hazard_other = Column(String(255), nullable=True)
    risk_title = Column(String(255))
    risk_category = Column(String(100))
    description = Column(Text)

    # Also from 068, also unmapped until now. Near misses carry the same pair
    # and the risk form asks the same two questions.
    potential_consequence = Column(String(255), nullable=True)
    underlying_cause = Column(String(255), nullable=True)

    likelihood = Column(String(50))
    consequence = Column(String(50))
    risk_score = Column(Integer)  # raw likelihood x consequence, 1-25

    # ── WF-01 · mandatory uplifts (migration 045) ─────────────────────────────
    # risk_score above stays the raw L x S so existing readers are unaffected.
    # adjusted_risk_score is raw + uplifts capped at 25, and it is the number
    # that bands the risk and decides whether work is blocked.
    # Produced by app.services.risk_scoring.score_risk.
    raw_risk_score = Column(Integer, nullable=True)
    uplift_no_valid_rams = Column(Integer, default=0)        # +2
    uplift_new_worker = Column(Integer, default=0)           # +1  under 30 days' service
    uplift_night_shift = Column(Integer, default=0)          # +1  22:00-06:00
    uplift_temporary_control = Column(Integer, default=0)    # +1
    uplift_total = Column(Integer, default=0)
    adjusted_risk_score = Column(Integer, nullable=True)
    risk_band = Column(String(20), nullable=True)            # Low | Medium | High | Critical
    risk_colour = Column(String(20), nullable=True)
    review_frequency = Column(String(20), nullable=True)
    approval_route = Column(String(40), nullable=True)       # Supervisor | Safety Manager | Executive
    blocks_work = Column(Integer, default=0)                 # adjusted >= 15
    risk_explanation = Column(Text, nullable=True)

    existing_controls = Column(Text)
    suggested_controls = Column(Text)

    reported_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
