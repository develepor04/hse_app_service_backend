from __future__ import annotations
from typing import Optional, Any
from datetime import date, datetime, time
from decimal import Decimal
from pydantic import BaseModel
from app.schemas.base import TimestampMixin


class RoleBase(BaseModel):
    role_name: str
    job_category: Optional[str] = None
    authority_level: Optional[int] = None
    permit_authority: Optional[str] = None
    safety_signatory: Optional[str] = None


class RoleCreate(RoleBase):
    pass


class RoleUpdate(BaseModel):
    role_name: Optional[str] = None
    job_category: Optional[str] = None
    authority_level: Optional[int] = None
    permit_authority: Optional[str] = None
    safety_signatory: Optional[str] = None


class RoleResponse(RoleBase, TimestampMixin):
    id: int

    model_config = {"from_attributes": True}
