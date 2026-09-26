from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text
from app.models.base import Base
from app.models.report_workflow_mixin import ReportWorkflowMixin


class UnsafeAct(Base, ReportWorkflowMixin):
    """A worker's observation of someone violating a safety rule.

    Separate from Incident: an unsafe act is a behaviour seen before anything went
    wrong, so it carries no injury fields and follows its own supervisor queue.
    """

    __tablename__ = "unsafe_acts"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    report_date = Column(Date)
    observed_date_time = Column(DateTime)
    location_station_id = Column(Integer, ForeignKey("working_stations.id"), nullable=True)

    act_type = Column(String(100))
    description = Column(Text)
    # Free text, not an FK: workers report what they saw, and the person involved may
    # be a contractor or someone they cannot identify by employee record.
    person_observed = Column(String(255))
    rule_violated = Column(String(255))
    corrective_advice_given = Column(String(10))

    reported_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
