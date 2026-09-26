from sqlalchemy import Column, ForeignKey, Integer, String
from app.models.base import Base


class TrainingProgram(Base):
    __tablename__ = "training_programs"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    training_name = Column(String(255), nullable=False)
    duration_hours = Column(Integer)
    frequency = Column(String(50))
    certification = Column(String(10))
    expiry_months = Column(Integer)
