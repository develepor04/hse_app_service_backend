from __future__ import annotations
from typing import Optional, Any
from datetime import date, datetime, time
from decimal import Decimal
from pydantic import BaseModel
from app.schemas.base import TimestampMixin


class TrainingProgramBase(BaseModel):
    training_name: str
    duration_hours: Optional[int] = None
    frequency: Optional[str] = None
    certification: Optional[str] = None
    expiry_months: Optional[int] = None


class TrainingProgramCreate(TrainingProgramBase):
    pass


class TrainingProgramUpdate(BaseModel):
    training_name: Optional[str] = None
    duration_hours: Optional[int] = None
    frequency: Optional[str] = None
    certification: Optional[str] = None
    expiry_months: Optional[int] = None


class TrainingProgramResponse(TrainingProgramBase, TimestampMixin):
    id: int

    model_config = {"from_attributes": True}
