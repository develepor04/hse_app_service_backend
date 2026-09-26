from __future__ import annotations
from typing import Optional, Any
from datetime import date, datetime, time
from decimal import Decimal
from pydantic import BaseModel
from app.schemas.base import TimestampMixin


class PermitToWorkBase(BaseModel):
    permit_type_id: int
    date_issued: date
    time_issued: Optional[time] = None
    location_station_id: Optional[int] = None
    work_description: Optional[str] = None
    duration_requested_hours: Optional[int] = None
    issued_by: Optional[int] = None
    approved_by: Optional[int] = None
    validity_start: Optional[datetime] = None
    validity_end: Optional[datetime] = None
    work_start_actual: Optional[datetime] = None
    work_end_actual: Optional[datetime] = None
    number_of_workers: Optional[int] = None
    status: Optional[str] = None
    deviation_reported: Optional[str] = None
    incident_occurred: Optional[str] = None


class PermitToWorkCreate(PermitToWorkBase):
    pass


class PermitToWorkUpdate(BaseModel):
    permit_type_id: Optional[int] = None
    date_issued: Optional[date] = None
    time_issued: Optional[time] = None
    location_station_id: Optional[int] = None
    work_description: Optional[str] = None
    duration_requested_hours: Optional[int] = None
    issued_by: Optional[int] = None
    approved_by: Optional[int] = None
    validity_start: Optional[datetime] = None
    validity_end: Optional[datetime] = None
    work_start_actual: Optional[datetime] = None
    work_end_actual: Optional[datetime] = None
    number_of_workers: Optional[int] = None
    status: Optional[str] = None
    deviation_reported: Optional[str] = None
    incident_occurred: Optional[str] = None


class PermitToWorkResponse(PermitToWorkBase, TimestampMixin):
    id: int

    model_config = {"from_attributes": True}
