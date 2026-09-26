from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text
from app.models.base import Base
from app.models.report_workflow_mixin import ReportWorkflowMixin


class NearMiss(Base, ReportWorkflowMixin):
    __tablename__ = "near_misses"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    report_date = Column(Date)
    event_date_time = Column(DateTime)
    location_station_id = Column(Integer, ForeignKey("working_stations.id"), nullable=True)
    description = Column(Text)
    potential_consequence = Column(String(255))
    hazard_id = Column(Integer, ForeignKey("hazards.id"), nullable=True)
    # Where and which hazard, when the worker picks "Other" — both ids above
    # are foreign keys and cannot hold free text. The id is left null and the
    # worker's own words kept here rather than forced onto the nearest wrong
    # option. See migration 069.
    location_other = Column(String(255), nullable=True)
    hazard_other = Column(String(255), nullable=True)
    underlying_cause = Column(String(255))
    # The worker's own answer to "how can we prevent this in the future?".
    # Named as risk_reports names the same thing (075).
    suggested_controls = Column(Text, nullable=True)
    control_failure = Column(String(10))
    reported_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    capa_escalation = Column(String(10))
