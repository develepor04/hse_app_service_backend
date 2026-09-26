from __future__ import annotations
from typing import Optional, Any
from datetime import date, datetime, time
from decimal import Decimal
from pydantic import BaseModel
from app.schemas.base import TimestampMixin


class HazardCategoryBase(BaseModel):
    category_name: str
    description: Optional[str] = None


class HazardCategoryCreate(HazardCategoryBase):
    pass


class HazardCategoryUpdate(BaseModel):
    category_name: Optional[str] = None
    description: Optional[str] = None


class HazardCategoryResponse(HazardCategoryBase, TimestampMixin):
    id: int

    model_config = {"from_attributes": True}
