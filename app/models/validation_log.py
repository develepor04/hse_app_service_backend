from sqlalchemy import Column, Integer, String, Text
from app.models.base import Base


class ValidationLog(Base):
    __tablename__ = "validation_logs"

    organisation_id = Column(Integer, nullable=True, index=True)
    file_name = Column(String(255), nullable=False)
    rule = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, default="pass")
    records_affected = Column(Integer, default=0)
    message = Column(Text, nullable=True)
    timestamp = Column(String(50), nullable=True)
