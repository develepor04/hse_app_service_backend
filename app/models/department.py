from sqlalchemy import Column, ForeignKey, Integer, String
from app.models.base import Base


class Department(Base):
    __tablename__ = "departments"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"))
    department_name = Column(String(255), nullable=False)
    manager_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    number_of_teams = Column(Integer)
