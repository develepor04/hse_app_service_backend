"""Module 4 (Assets & Operations) equipment/asset register — the client's
own Assets_Sample_Data.xlsx (Assets_Register sheet). Unlocks the Module 4
KPIs that were previously flagged not computable for lack of any CMMS/asset
register data: MTBF, PM Compliance (proxy), and SCE Overdue Count.

Distinct from app/models/equipment_certification.py (EquipmentCertification),
which tracks compliance *certificates* per piece of equipment — this table is
the maintenance/reliability register (PM schedule, operating hours, MTBF,
failure history), a different real-world record the client provided
separately.
"""
from sqlalchemy import Column, Date, ForeignKey, Integer, Numeric, String

from app.models.aiisms_mixin import AiIsmsMetadataMixin
from app.models.base import Base


class Equipment(Base, AiIsmsMetadataMixin):
    __tablename__ = "equipment"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    # Client's own code (e.g. "EQ-001") — not a surrogate for this table's own id.
    equipment_code = Column(String(50), nullable=False, index=True)
    equipment_name = Column(String(255), nullable=False)
    equipment_type = Column(String(120), nullable=True, index=True)
    # Client's own station code (e.g. "STN001") — same pattern as
    # ContractorWorker.badge_no: not FK'd to working_stations, which has no
    # matching code field, only a free-text station_name.
    location_station = Column(String(50), nullable=True)
    installation_date = Column(Date, nullable=True)
    pm_interval_days = Column(Integer, nullable=True)
    last_pm_date = Column(Date, nullable=True)
    next_pm_due = Column(Date, nullable=True)
    operating_hours_ytd = Column(Integer, nullable=True)
    last_failure_date = Column(Date, nullable=True)
    mtbf_hours_estimated = Column(Numeric(10, 2), nullable=True)
    safety_critical_sce = Column(Integer, nullable=False, default=0)
    status = Column(String(30), nullable=True, index=True)
