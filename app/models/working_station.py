from sqlalchemy import Column, ForeignKey, Integer, String, Text
from app.models.base import Base


class WorkingStation(Base):
    __tablename__ = "working_stations"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    station_name = Column(String(255), nullable=False)
    site_id = Column(Integer, ForeignKey("sites.id"))
    department = Column(String(255))
    zone_classification = Column(String(100))
    primary_hazard_id = Column(Integer, ForeignKey("hazards.id"), nullable=True)
    staffing_requirement = Column(Integer)
    equipment_list = Column(Text)
    permit_types_required = Column(String(255))
    access_restrictions = Column(String(255))
