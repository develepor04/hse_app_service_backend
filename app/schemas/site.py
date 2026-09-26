from __future__ import annotations
from typing import Optional, Any
from datetime import date, datetime, time
from decimal import Decimal
from pydantic import BaseModel
from app.schemas.base import TimestampMixin


class SiteBase(BaseModel):
    site_name: str
    address: Optional[str] = None
    postcode: Optional[str] = None
    city: Optional[str] = None
    type: Optional[str] = None
    operational_status: Optional[str] = None
    number_of_working_stations: Optional[int] = None
    capacity: Optional[int] = None
    primary_products: Optional[str] = None
    hazard_classification: Optional[str] = None


class SiteCreate(SiteBase):
    pass


class SiteUpdate(BaseModel):
    site_name: Optional[str] = None
    address: Optional[str] = None
    postcode: Optional[str] = None
    city: Optional[str] = None
    type: Optional[str] = None
    operational_status: Optional[str] = None
    number_of_working_stations: Optional[int] = None
    capacity: Optional[int] = None
    primary_products: Optional[str] = None
    hazard_classification: Optional[str] = None


class SiteResponse(SiteBase, TimestampMixin):
    id: int

    model_config = {"from_attributes": True}
