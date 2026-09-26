"""Schemas for WF-09 · Transport & Logistics."""
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class VehicleCreate(BaseModel):
    registration: str = Field(..., min_length=1)
    qr_code: Optional[str] = None
    vehicle_type: Optional[str] = None
    make_model: Optional[str] = None
    site_id: Optional[int] = None
    roadworthiness_expiry: Optional[date] = None
    insurance_expiry: Optional[date] = None


class VehicleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    registration: str
    qr_code: Optional[str] = None
    vehicle_type: Optional[str] = None
    make_model: Optional[str] = None
    site_id: Optional[int] = None
    roadworthiness_expiry: Optional[date] = None
    insurance_expiry: Optional[date] = None
    last_inspection_at: Optional[datetime] = None
    defect_status: str
    defect_notes: Optional[str] = None
    active: int = 1


class VehicleInspection(BaseModel):
    """Pre-trip check. A major defect or a grounded vehicle blocks departure."""

    defect_status: str = Field("none", pattern="^(none|minor|major|grounded)$")
    defect_notes: Optional[str] = None


class JourneyPlanCreate(BaseModel):
    """JRS = Route(1-3) x Mode(1-4) x Cargo(1-3)."""

    vehicle_id: Optional[int] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    transport_mode: str = Field("road", pattern="^(road|rail|marine|air)$")
    route_score: int = Field(1, ge=1, le=3)
    mode_score: int = Field(1, ge=1, le=4)
    cargo_score: int = Field(1, ge=1, le=3)
    planned_departure: Optional[datetime] = None
    planned_arrival: Optional[datetime] = None
    comms_protocol: Optional[str] = None
    weather: Optional[Dict[str, Any]] = None


class JourneyPlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    vehicle_id: Optional[int] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    transport_mode: str
    route_score: int
    mode_score: int
    cargo_score: int
    journey_risk_score: int
    risk_band: str
    status: str
    requires_authorisation: int = 0
    authorised_by: Optional[int] = None
    authorised_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    planned_departure: Optional[datetime] = None
    planned_arrival: Optional[datetime] = None
    actual_departure: Optional[datetime] = None
    actual_arrival: Optional[datetime] = None
    checkin_interval_minutes: int
    comms_protocol: Optional[str] = None
    pretrip_completed_at: Optional[datetime] = None
    pretrip_defects: Optional[str] = None


class JourneyAuthorise(BaseModel):
    approved: bool = True
    checkin_interval_minutes: Optional[int] = None
    comms_protocol: Optional[str] = None
    rejection_reason: Optional[str] = None


class PreTripCheck(BaseModel):
    vehicle_id: Optional[int] = None
    defects: Optional[str] = None
    defect_status: str = Field("none", pattern="^(none|minor|major|grounded)$")


class CheckInCreate(BaseModel):
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None
    defects_reported: Optional[str] = None
    deviations: Optional[str] = None
    notes: Optional[str] = None


class CheckInResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    journey_plan_id: int
    sequence_no: int
    due_at: datetime
    checked_in_at: Optional[datetime] = None
    missed: int = 0
    escalated_at: Optional[datetime] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None
    defects_reported: Optional[str] = None
    deviations: Optional[str] = None
    notes: Optional[str] = None


class CheckInMonitorRow(BaseModel):
    """Live journey board for the supervisor's check-in monitor."""

    journey_plan_id: int
    employee_id: int
    employee_name: Optional[str] = None
    destination: Optional[str] = None
    risk_band: str
    status: str
    next_due_at: Optional[datetime] = None
    minutes_overdue: Optional[int] = None
    missed_count: int = 0
    is_escalated: bool = False


class WeatherLimitCreate(BaseModel):
    transport_mode: str = Field(..., pattern="^(road|rail|marine|air)$")
    max_wind_kph: Optional[float] = None
    min_visibility_m: Optional[float] = None
    max_precip_mm_hr: Optional[float] = None
    max_wave_height_m: Optional[float] = None
    notes: Optional[str] = None


class TransportKpiResponse(BaseModel):
    """Monthly transport KPI batch — weather limits by mode, fatigue flag rate,
    defect rate, check-in completeness."""

    period_days: int
    journeys_total: int
    journeys_high_risk: int
    authorisation_rate: float
    checkins_due: int
    checkins_missed: int
    checkin_completeness: float
    vehicles_with_defects: int
    fatigue_flag_rate: float
    by_mode: Dict[str, int]
