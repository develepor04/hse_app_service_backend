from sqlalchemy import Column, Integer, String, Text, ForeignKey
from app.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    organisation_id = Column(Integer, ForeignKey("organisation.id", ondelete="CASCADE"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(100), nullable=False)
    module = Column(String(100), nullable=False)
    record_id = Column(String(100), nullable=True)
    previous_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    ip_address = Column(String(64), nullable=True)
