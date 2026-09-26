"""WF-09 · Transport & Logistics.

    JRS = Route(1-3) x Mode(1-4) x Cargo(1-3)

    1-4  low
    5-12 medium
    >=13 high — requires Transport Authorisation

Check-in: road every 2 h, marine per voyage plan, air per flight plan.
A missed check-in escalates to the control room.
"""
from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text

from app.models.aiisms_mixin import AiIsmsMetadataMixin
from app.models.base import Base


class Vehicle(Base, AiIsmsMetadataMixin):
    __tablename__ = "vehicles"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    registration = Column(String(60), nullable=False, index=True)
    qr_code = Column(String(120), nullable=True, index=True)
    vehicle_type = Column(String(120), nullable=True)
    make_model = Column(String(200), nullable=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)

    roadworthiness_expiry = Column(Date, nullable=True)
    insurance_expiry = Column(Date, nullable=True)
    last_inspection_at = Column(DateTime, nullable=True)
    defect_status = Column(String(20), nullable=False, default="none")
    defect_notes = Column(Text, nullable=True)
    active = Column(Integer, nullable=False, default=1)


class WeatherLimitTable(Base, AiIsmsMetadataMixin):
    __tablename__ = "weather_limit_tables"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    transport_mode = Column(String(30), nullable=False, index=True)
    max_wind_kph = Column(Numeric(6, 2), nullable=True)
    min_visibility_m = Column(Numeric(8, 2), nullable=True)
    max_precip_mm_hr = Column(Numeric(6, 2), nullable=True)
    max_wave_height_m = Column(Numeric(6, 2), nullable=True)
    notes = Column(Text, nullable=True)


class JourneyPlan(Base, AiIsmsMetadataMixin):
    __tablename__ = "journey_plans"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=True)

    origin = Column(String(200), nullable=True)
    destination = Column(String(200), nullable=True)
    transport_mode = Column(String(30), nullable=False, default="road")

    route_score = Column(Integer, nullable=False, default=1)
    mode_score = Column(Integer, nullable=False, default=1)
    cargo_score = Column(Integer, nullable=False, default=1)
    journey_risk_score = Column(Integer, nullable=False, default=1)
    risk_band = Column(String(20), nullable=False, default="low")

    status = Column(String(30), nullable=False, default="draft", index=True)
    requires_authorisation = Column(Integer, nullable=False, default=0)
    authorised_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    authorised_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)

    planned_departure = Column(DateTime, nullable=True)
    planned_arrival = Column(DateTime, nullable=True)
    actual_departure = Column(DateTime, nullable=True)
    actual_arrival = Column(DateTime, nullable=True)

    checkin_interval_minutes = Column(Integer, nullable=False, default=120)
    comms_protocol = Column(String(200), nullable=True)
    pretrip_completed_at = Column(DateTime, nullable=True)
    pretrip_defects = Column(Text, nullable=True)
    weather_snapshot = Column(JSON, nullable=True)


class CheckInEvent(Base, AiIsmsMetadataMixin):
    __tablename__ = "check_in_events"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    journey_plan_id = Column(Integer, ForeignKey("journey_plans.id"), nullable=False, index=True)
    sequence_no = Column(Integer, nullable=False, default=1)
    due_at = Column(DateTime, nullable=False, index=True)
    checked_in_at = Column(DateTime, nullable=True)
    missed = Column(Integer, nullable=False, default=0, index=True)
    escalated_at = Column(DateTime, nullable=True)
    escalated_to = Column(Integer, ForeignKey("employees.id"), nullable=True)

    gps_latitude = Column(Numeric(10, 7), nullable=True)
    gps_longitude = Column(Numeric(10, 7), nullable=True)
    defects_reported = Column(Text, nullable=True)
    deviations = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
