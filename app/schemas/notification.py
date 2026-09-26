from __future__ import annotations
from typing import Optional
from datetime import datetime
from pydantic import BaseModel
from app.schemas.base import TimestampMixin


class NotificationCreate(BaseModel):
    title: str
    message: str
    type: str = "info"
    target_type: str = "all"
    target_invite_id: Optional[int] = None


class NotificationOut(TimestampMixin):
    id: int
    organisation_id: Optional[int]
    title: str
    message: str
    type: str
    target_type: str
    status: str
    sent_at: Optional[datetime]
    is_read: bool = False
    # Migration 061. `category` lets a client group the CAPA chase separately
    # from announcements, and `subject_ref` lets it deep-link to the action
    # rather than making the user go and find CAPA-000231 by hand.
    target_employee_id: Optional[int] = None
    category: Optional[str] = None
    subject_ref: Optional[str] = None

    model_config = {"from_attributes": True}


class UnreadCountOut(BaseModel):
    count: int
