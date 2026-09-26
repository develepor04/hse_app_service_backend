from sqlalchemy import Column, Date, Integer, JSON, String
from app.models.base import Base


class Organisation(Base):
    __tablename__ = "organisation"

    organisation_name = Column(String(255), nullable=False)
    country = Column(String(100))
    industry_sector = Column(String(100))
    number_of_employees = Column(Integer)
    headquarters_location = Column(String(255))
    parent_company = Column(String(255))
    iso_45001_status = Column(String(50))
    regulatory_authority = Column(String(255))
    establishment_date = Column(Date)
    compliance_config = Column(JSON, nullable=True)
    branding = Column(JSON, nullable=True)
    formula_config = Column(JSON, nullable=True)
