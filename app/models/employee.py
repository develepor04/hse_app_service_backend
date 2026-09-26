from sqlalchemy import Column, Date, ForeignKey, Integer, String
from app.models.base import Base


class Employee(Base):
    __tablename__ = "employees"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    full_name = Column(String(255), nullable=False)
    date_of_birth = Column(Date)
    gender = Column(String(1))
    employment_type = Column(String(50))
    employment_start_date = Column(Date)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    shift_pattern = Column(String(50))
    manager_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    induction_date = Column(Date)
    active_status = Column(String(20))
