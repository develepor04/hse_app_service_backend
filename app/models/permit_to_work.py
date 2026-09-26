from sqlalchemy import JSON, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, Time
from app.models.base import Base


class PermitToWork(Base):
    __tablename__ = "permits_to_work"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    permit_type_id = Column(Integer, ForeignKey("permit_types.id"))
    date_issued = Column(Date, nullable=False)
    time_issued = Column(Time)
    location_station_id = Column(Integer, ForeignKey("working_stations.id"), nullable=True)
    work_description = Column(Text)
    duration_requested_hours = Column(Integer)
    issued_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    approved_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    validity_start = Column(DateTime)
    validity_end = Column(DateTime)
    work_start_actual = Column(DateTime)
    work_end_actual = Column(DateTime)
    number_of_workers = Column(Integer)
    status = Column(String(50))
    deviation_reported = Column(String(10))
    incident_occurred = Column(String(10))

    # ── Worker → Supervisor → Manager → Auditor workflow (migration 031) ──────
    # `status` above stays the website's field (it counts status='Active'); the app
    # state machine rides on workflow_status and only flips status to 'Active' on
    # manager approval.
    workflow_status = Column(String(50), default="requested")
    requested_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    requested_at = Column(DateTime, nullable=True)
    acknowledged_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    supervisor_notes = Column(Text, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    # Stage 04 INVESTIGATE — why live work was stopped (migration 058).
    suspension_reason = Column(Text, nullable=True)
    auditor_verified_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    auditor_verified_at = Column(DateTime, nullable=True)
    verification_result = Column(String(50), nullable=True)  # valid | invalid | not_displayed
    verification_notes = Column(Text, nullable=True)

    # ── Deterministic gate engine (migration 044) ────────────────────────────
    # The permit is where five of the six gates land, so it carries the verdict
    # and the inputs the gates read.
    gate_status = Column(String(20), nullable=True)  # pass | amber | block
    gate_checked_at = Column(DateTime, nullable=True)
    gate_blocked_reason = Column(Text, nullable=True)
    contractor_company_id = Column(Integer, ForeignKey("contractor_companies.id"), nullable=True)
    rams_score_id = Column(Integer, nullable=True)
    # B -> PERMIT. Which Flow B assessment authorises this work. The gate
    # reads it rather than inferring one from the work description — see
    # gate_engine.gate_rams_linked and migration 071.
    risk_assessment_id = Column(Integer, nullable=True)
    zone = Column(String(120), nullable=True)
    is_high_energy = Column(Integer, nullable=False, default=0)
    gps_latitude = Column(Numeric(10, 7), nullable=True)
    gps_longitude = Column(Numeric(10, 7), nullable=True)

    # The risk assessment (JSA) the worker attached when they raised it, in the
    # same shape the five report families use. Not the same thing as
    # `risk_assessment_id` above: that is the Flow-B assessment the gate engine
    # requires, this is what the worker had in their hand. See migration 077.
    evidence_json = Column(JSON, nullable=True)
