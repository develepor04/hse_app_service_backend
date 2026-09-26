from __future__ import annotations
from typing import Optional, Any
from datetime import date, datetime, time
from decimal import Decimal
from pydantic import BaseModel
from app.schemas.base import TimestampMixin


class IncidentBase(BaseModel):
    report_date: Optional[date] = None
    incident_date_time: Optional[datetime] = None
    location_station_id: Optional[int] = None
    incident_type: Optional[str] = None
    severity: Optional[str] = None
    number_persons_involved: Optional[int] = None
    description: Optional[str] = None
    immediate_cause: Optional[str] = None
    root_cause: Optional[str] = None
    hazard_id: Optional[int] = None
    permit_active: Optional[str] = None
    control_failure: Optional[str] = None
    reported_by: Optional[int] = None
    investigation_status: Optional[str] = None
    capa_generated: Optional[str] = None
    days_away: Optional[int] = None
    root_cause_category: Optional[str] = None
    source: Optional[str] = None


class IncidentCreate(IncidentBase):
    pass


class IncidentUpdate(BaseModel):
    report_date: Optional[date] = None
    incident_date_time: Optional[datetime] = None
    location_station_id: Optional[int] = None
    incident_type: Optional[str] = None
    severity: Optional[str] = None
    number_persons_involved: Optional[int] = None
    description: Optional[str] = None
    immediate_cause: Optional[str] = None
    root_cause: Optional[str] = None
    hazard_id: Optional[int] = None
    permit_active: Optional[str] = None
    control_failure: Optional[str] = None
    reported_by: Optional[int] = None
    investigation_status: Optional[str] = None
    capa_generated: Optional[str] = None
    days_away: Optional[int] = None
    root_cause_category: Optional[str] = None


class IncidentResponse(IncidentBase, TimestampMixin):
    id: int

    model_config = {"from_attributes": True}


class IncidentPage(BaseModel):
    data: list[IncidentResponse]
    total: int
    page: int
    pageSize: int
    totalPages: int
