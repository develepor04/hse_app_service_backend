from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, func
from app.models.base import Base


class EquipmentCertification(Base):
    __tablename__ = "equipment_certifications"

    organisation_id     = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    equipment_name      = Column(String(255), nullable=False)
    equipment_type      = Column(String(100))
    site_id             = Column(Integer, ForeignKey("sites.id"), nullable=True)
    zone                = Column(String(100))
    serial_number       = Column(String(100))
    manufacturer        = Column(String(255))
    model               = Column(String(100))
    certification_type  = Column(String(100))
    certified_by        = Column(String(255))
    issue_date          = Column(Date)
    expiry_date         = Column(Date)
    next_inspection_date = Column(Date)
    compliance_standard = Column(String(100))
    created_at          = Column(DateTime, server_default=func.now())
