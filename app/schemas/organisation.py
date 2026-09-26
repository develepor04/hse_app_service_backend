from __future__ import annotations
from typing import Optional, Any
from datetime import date, datetime, time
from decimal import Decimal
from pydantic import BaseModel
from app.schemas.base import TimestampMixin


class OrganisationBase(BaseModel):
    organisation_name: str
    country: Optional[str] = None
    industry_sector: Optional[str] = None
    number_of_employees: Optional[int] = None
    headquarters_location: Optional[str] = None
    parent_company: Optional[str] = None
    iso_45001_status: Optional[str] = None
    regulatory_authority: Optional[str] = None
    establishment_date: Optional[date] = None


class OrganisationCreate(OrganisationBase):
    pass


class OrganisationUpdate(BaseModel):
    organisation_name: Optional[str] = None
    country: Optional[str] = None
    industry_sector: Optional[str] = None
    number_of_employees: Optional[int] = None
    headquarters_location: Optional[str] = None
    parent_company: Optional[str] = None
    iso_45001_status: Optional[str] = None
    regulatory_authority: Optional[str] = None
    establishment_date: Optional[date] = None


class OrganisationResponse(OrganisationBase, TimestampMixin):
    id: int

    model_config = {"from_attributes": True}
