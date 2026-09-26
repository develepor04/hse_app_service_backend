from sqlalchemy import Column, Date, ForeignKey, Integer, String
from app.models.base import Base


class Policy(Base):
    __tablename__ = "policies"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    policy_name = Column(String(255), nullable=False)
    category = Column(String(100))
    issue_date = Column(Date)
    owner = Column(String(100))
    status = Column(String(50))
