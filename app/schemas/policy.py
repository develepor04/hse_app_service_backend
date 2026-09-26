from __future__ import annotations
from typing import Optional, Any
from datetime import date, datetime, time
from decimal import Decimal
from pydantic import BaseModel
from app.schemas.base import TimestampMixin


class PolicyBase(BaseModel):
    policy_name: str
    category: Optional[str] = None
    issue_date: Optional[date] = None
    owner: Optional[str] = None
    status: Optional[str] = None


class PolicyCreate(PolicyBase):
    pass


class PolicyUpdate(BaseModel):
    policy_name: Optional[str] = None
    category: Optional[str] = None
    issue_date: Optional[date] = None
    owner: Optional[str] = None
    status: Optional[str] = None


class PolicyResponse(PolicyBase, TimestampMixin):
    id: int

    model_config = {"from_attributes": True}
