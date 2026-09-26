from sqlalchemy import Column, Integer, String, Text
from app.models.base import Base


class Document(Base):
    __tablename__ = "documents"

    organisation_id = Column(Integer, nullable=True, index=True)
    file_name = Column(String(255), nullable=False)
    file_type = Column(String(20), nullable=False)
    category = Column(String(20), nullable=False, default="pdf")
    record_type = Column(String(100), nullable=True)
    size = Column(String(30), nullable=True)
    uploaded_by = Column(String(255), default="Admin")
    file_path = Column(Text, nullable=True)
