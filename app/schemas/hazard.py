from __future__ import annotations
from typing import Optional, Any
from datetime import date, datetime, time
from decimal import Decimal
from pydantic import BaseModel
from app.schemas.base import TimestampMixin


class HazardBase(BaseModel):
    category_id: Optional[int] = None   # optional so manual entry can omit it
    hazard_name: str
    severity: Optional[str] = None
    probability: Optional[str] = None


class HazardCreate(HazardBase):
    pass


class HazardUpdate(BaseModel):
    category_id: Optional[int] = None
    hazard_name: Optional[str] = None
    severity: Optional[str] = None
    probability: Optional[str] = None


class HazardResponse(HazardBase, TimestampMixin):
    id: int

    model_config = {"from_attributes": True}
