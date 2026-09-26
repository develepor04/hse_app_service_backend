from __future__ import annotations
from typing import Optional, Any
from datetime import date, datetime, time
from decimal import Decimal
from pydantic import BaseModel
from app.schemas.base import TimestampMixin


class ShiftScheduleBase(BaseModel):
    employee_id: int
    shift_date: date
    shift_type: Optional[str] = None
    shift_start: Optional[time] = None
    shift_end: Optional[time] = None
    actual_hours_worked: Optional[Decimal] = None
    station_id: Optional[int] = None
    supervisor_id: Optional[int] = None


class ShiftScheduleCreate(ShiftScheduleBase):
    pass


class ShiftScheduleUpdate(BaseModel):
    employee_id: Optional[int] = None
    shift_date: Optional[date] = None
    shift_type: Optional[str] = None
    shift_start: Optional[time] = None
    shift_end: Optional[time] = None
    actual_hours_worked: Optional[Decimal] = None
    station_id: Optional[int] = None
    supervisor_id: Optional[int] = None


class ShiftScheduleResponse(ShiftScheduleBase, TimestampMixin):
    id: int

    model_config = {"from_attributes": True}
