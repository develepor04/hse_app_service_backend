from __future__ import annotations
from typing import Optional, Any
from datetime import date, datetime, time
from decimal import Decimal
from pydantic import BaseModel
from app.schemas.base import TimestampMixin


class DepartmentBase(BaseModel):
    site_id: int
    department_name: str
    manager_id: Optional[int] = None
    number_of_teams: Optional[int] = None


class DepartmentCreate(DepartmentBase):
    pass


class DepartmentUpdate(BaseModel):
    site_id: Optional[int] = None
    department_name: Optional[str] = None
    manager_id: Optional[int] = None
    number_of_teams: Optional[int] = None


class DepartmentResponse(DepartmentBase, TimestampMixin):
    id: int

    model_config = {"from_attributes": True}
