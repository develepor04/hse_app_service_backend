from sqlalchemy import Column, Integer, String
from app.models.base import Base


class DataImport(Base):
    __tablename__ = "data_imports"

    organisation_id = Column(Integer, nullable=True, index=True)
    file_name = Column(String(255), nullable=False)
    import_type = Column(String(50), nullable=False, default="excel")
    data_type = Column(String(100), nullable=False)
    records_total = Column(Integer, default=0)
    records_success = Column(Integer, default=0)
    records_failed = Column(Integer, default=0)
    status = Column(String(50), default="success")
    uploaded_by = Column(String(255), default="Admin")
