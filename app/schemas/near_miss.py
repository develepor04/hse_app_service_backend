from __future__ import annotations
from typing import Optional, Any
from datetime import date, datetime, time
from decimal import Decimal
from pydantic import BaseModel
from app.schemas.base import TimestampMixin


class NearMissBase(BaseModel):
    report_date: Optional[date] = None
    event_date_time: Optional[datetime] = None
    location_station_id: Optional[int] = None
    description: Optional[str] = None
    potential_consequence: Optional[str] = None
    hazard_id: Optional[int] = None
    underlying_cause: Optional[str] = None
    control_failure: Optional[str] = None
    reported_by: Optional[int] = None
    capa_escalation: Optional[str] = None


class NearMissCreate(NearMissBase):
    pass


class NearMissUpdate(BaseModel):
    report_date: Optional[date] = None
    event_date_time: Optional[datetime] = None
    location_station_id: Optional[int] = None
    description: Optional[str] = None
    potential_consequence: Optional[str] = None
    hazard_id: Optional[int] = None
    underlying_cause: Optional[str] = None
    control_failure: Optional[str] = None
    reported_by: Optional[int] = None
    capa_escalation: Optional[str] = None


class NearMissResponse(NearMissBase, TimestampMixin):
    id: int

    model_config = {"from_attributes": True}
