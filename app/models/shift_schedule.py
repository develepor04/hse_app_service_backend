from sqlalchemy import Column, Date, ForeignKey, Integer, Numeric, String, Time
from app.models.base import Base


class ShiftSchedule(Base):
    __tablename__ = "shift_schedule"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"))
    shift_date = Column(Date, nullable=False)
    shift_type = Column(String(50))
    shift_start = Column(Time)
    shift_end = Column(Time)
    actual_hours_worked = Column(Numeric(4,1))
    station_id = Column(Integer, ForeignKey("working_stations.id"), nullable=True)
    supervisor_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
