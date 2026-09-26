from __future__ import annotations
from typing import Optional, Any
from datetime import date, datetime, time
from decimal import Decimal
from pydantic import BaseModel
from app.schemas.base import TimestampMixin


class PermitTypeBase(BaseModel):
    permit_type_name: str
    risk_level: Optional[str] = None
    validity_period_hours: Optional[int] = None
    concurrent_limit: Optional[int] = None


class PermitTypeCreate(PermitTypeBase):
    pass


class PermitTypeUpdate(BaseModel):
    permit_type_name: Optional[str] = None
    risk_level: Optional[str] = None
    validity_period_hours: Optional[int] = None
    concurrent_limit: Optional[int] = None


class PermitTypeResponse(PermitTypeBase, TimestampMixin):
    id: int

    model_config = {"from_attributes": True}
