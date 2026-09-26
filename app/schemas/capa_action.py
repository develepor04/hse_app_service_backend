from __future__ import annotations
from typing import Optional, Any
from datetime import date, datetime, time
from decimal import Decimal
from pydantic import BaseModel
from app.schemas.base import TimestampMixin


class CapaActionBase(BaseModel):
    incident_id: Optional[int] = None
    action_type: Optional[str] = None
    description: Optional[str] = None
    root_cause_addressed: Optional[str] = None
    responsible_person_id: Optional[int] = None
    due_date: Optional[date] = None
    status: Optional[str] = None
    effectiveness_rating: Optional[int] = None


class CapaActionCreate(CapaActionBase):
    pass


class CapaActionUpdate(BaseModel):
    incident_id: Optional[int] = None
    action_type: Optional[str] = None
    description: Optional[str] = None
    root_cause_addressed: Optional[str] = None
    responsible_person_id: Optional[int] = None
    due_date: Optional[date] = None
    status: Optional[str] = None
    effectiveness_rating: Optional[int] = None


class CapaActionResponse(CapaActionBase, TimestampMixin):
    id: int

    model_config = {"from_attributes": True}
