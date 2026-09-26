from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from app.models.base import Base


class SafetyWalk(Base):
    __tablename__ = "safety_walks"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    inspection_date_time = Column(DateTime)
    location_station_id = Column(Integer, ForeignKey("working_stations.id"), nullable=True)
    inspector_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    inspection_type = Column(String(100))
    issues_found = Column(Integer)
    critical_issues = Column(Integer)
    housekeeping_rating = Column(Integer)
    compliance_rating = Column(Integer)
    follow_up_required = Column(String(10))
