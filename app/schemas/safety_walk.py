from __future__ import annotations
from typing import Optional, Any
from datetime import date, datetime, time
from decimal import Decimal
from pydantic import BaseModel
from app.schemas.base import TimestampMixin


class SafetyWalkBase(BaseModel):
    inspection_date_time: Optional[datetime] = None
    location_station_id: Optional[int] = None
    inspector_id: Optional[int] = None
    inspection_type: Optional[str] = None
    issues_found: Optional[int] = None
    critical_issues: Optional[int] = None
    housekeeping_rating: Optional[int] = None
    compliance_rating: Optional[int] = None
    follow_up_required: Optional[str] = None


class SafetyWalkCreate(SafetyWalkBase):
    pass


class SafetyWalkUpdate(BaseModel):
    inspection_date_time: Optional[datetime] = None
    location_station_id: Optional[int] = None
    inspector_id: Optional[int] = None
    inspection_type: Optional[str] = None
    issues_found: Optional[int] = None
    critical_issues: Optional[int] = None
    housekeeping_rating: Optional[int] = None
    compliance_rating: Optional[int] = None
    follow_up_required: Optional[str] = None


class SafetyWalkResponse(SafetyWalkBase, TimestampMixin):
    id: int

    model_config = {"from_attributes": True}
