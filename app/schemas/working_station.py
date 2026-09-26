from __future__ import annotations
from typing import Optional, Any
from datetime import date, datetime, time
from decimal import Decimal
from pydantic import BaseModel
from app.schemas.base import TimestampMixin


class WorkingStationBase(BaseModel):
    station_name: str
    site_id: int
    department: Optional[str] = None
    zone_classification: Optional[str] = None
    primary_hazard_id: Optional[int] = None
    staffing_requirement: Optional[int] = None
    equipment_list: Optional[str] = None
    permit_types_required: Optional[str] = None
    access_restrictions: Optional[str] = None


class WorkingStationCreate(WorkingStationBase):
    pass


class WorkingStationUpdate(BaseModel):
    station_name: Optional[str] = None
    site_id: Optional[int] = None
    department: Optional[str] = None
    zone_classification: Optional[str] = None
    primary_hazard_id: Optional[int] = None
    staffing_requirement: Optional[int] = None
    equipment_list: Optional[str] = None
    permit_types_required: Optional[str] = None
    access_restrictions: Optional[str] = None


class WorkingStationResponse(WorkingStationBase, TimestampMixin):
    id: int

    model_config = {"from_attributes": True}
