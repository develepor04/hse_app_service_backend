from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.mysql import JSON
from app.models.base import Base


class Incident(Base):
    __tablename__ = "incidents"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    report_date = Column(Date)
    incident_date_time = Column(DateTime)
    location_station_id = Column(Integer, ForeignKey("working_stations.id"), nullable=True)
    incident_type = Column(String(100))
    severity = Column(String(50))
    number_persons_involved = Column(Integer)
    description = Column(Text)
    immediate_cause = Column(String(255))
    root_cause = Column(String(255))
    hazard_id = Column(Integer, ForeignKey("hazards.id"), nullable=True)
    permit_active = Column(String(10))
    control_failure = Column(String(10))
    reported_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    investigation_status = Column(String(50))
    # Mobile App | Web App | Data Import | Legacy (migration 077 backfill for
    # rows that predate this column). Set explicitly by every write path —
    # worker.py's /worker/incidents, the web registration form, and the Excel
    # importer — not inferred from whether GPS happened to be present.
    source = Column(String(20), nullable=True)
    capa_generated = Column(String(10))
    days_away = Column(Integer)
    root_cause_category = Column(String(100))

    # ── Workflow Status ───────────────────────────────────────────────────────
    # reported | acknowledged | under_investigation | escalated | pending_approval | closed
    workflow_status = Column(String(50), default="reported")

    # ── Assignment & Escalation ───────────────────────────────────────────────
    assigned_supervisor_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    escalated_to_manager_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    escalation_reason = Column(Text, nullable=True)

    # ── SLA Timestamps ────────────────────────────────────────────────────────
    reported_at = Column(DateTime, nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    investigation_started_at = Column(DateTime, nullable=True)
    investigation_completed_at = Column(DateTime, nullable=True)
    escalated_at = Column(DateTime, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)

    # ── Manager Closure Fields ────────────────────────────────────────────────
    closure_notes = Column(Text, nullable=True)
    regulatory_notified = Column(String(10), default="No")
    lessons_learned = Column(Text, nullable=True)
    communicated_to_teams = Column(String(10), default="No")
    manager_signature = Column(String(255), nullable=True)

    # ── Worker Report Extra Fields ────────────────────────────────────────────
    anyone_injured = Column(String(10), default="No")
    injured_person_name = Column(String(255), nullable=True)
    injured_body_part = Column(String(255), nullable=True)
    hazard_still_present = Column(String(10), default="No")
    witnesses_json = Column(JSON, nullable=True)
    evidence_json = Column(JSON, nullable=True)
    gps_latitude = Column(Numeric(10, 8), nullable=True)
    gps_longitude = Column(Numeric(11, 8), nullable=True)

    # ── Supervisor Investigation Fields ───────────────────────────────────────
    five_why_analysis = Column(JSON, nullable=True)
    immediate_actions_taken = Column(Text, nullable=True)
    supervisor_signature = Column(String(255), nullable=True)
    severity_classification = Column(String(50), nullable=True)  # LTI | MTI | First Aid | Near Miss

    # ── WF-03 · P1-P5 severity (migration 045) ────────────────────────────────
    # `severity` and `severity_classification` above are the legacy free-text and
    # LTI/MTI taxonomy the website still reads. `severity_priority` is the
    # spec's system-enforced classification and is the one that drives the
    # investigation SLA and the statutory deadline.
    # Produced by app.services.incident_severity.classify_severity.
    severity_priority = Column(String(4), nullable=True)          # P1 | P2 | P3 | P4 | P5
    severity_label = Column(String(60), nullable=True)
    treatment_level = Column(String(40), nullable=True)           # Q2 answer
    dangerous_occurrence = Column(Integer, default=0)             # Q3
    worst_case_fatal = Column(Integer, default=0)                 # Q4 input
    is_hipo = Column(Integer, default=0)                          # Q4 verdict
    is_recurring_pattern = Column(Integer, default=0)             # Q5
    requires_systemic_rca = Column(Integer, default=0)
    severity_trace = Column(Text, nullable=True)                  # which questions decided it
    severity_classified_at = Column(DateTime, nullable=True)
    investigation_due_at = Column(DateTime, nullable=True)
    min_investigator = Column(String(60), nullable=True)

    # ── Appendix A · statutory notification (migration 045) ───────────────────
    # A drafted obligation, never a submission. statutory_authorised_* is the
    # human gate the spec requires before anything reaches a regulator.
    statutory_reportable = Column(Integer, default=0)
    statutory_jurisdiction = Column(String(8), nullable=True)
    statutory_regulator = Column(String(120), nullable=True)
    statutory_obligations = Column(JSON, nullable=True)
    statutory_due_at = Column(DateTime, nullable=True)
    statutory_summary = Column(String(500), nullable=True)
    statutory_authorised_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    statutory_authorised_at = Column(DateTime, nullable=True)
    statutory_reference = Column(String(120), nullable=True)

    # ── Stage 06 VERIFY · did the corrective action work? (migration 054) ─────
    # Distinct from the auditor trio below: this is the manager's in-workflow
    # sign-off that the CAPA held, not the auditor's post-closure review.
    capa_verified_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    capa_verified_at = Column(DateTime, nullable=True)
    capa_verification_notes = Column(Text, nullable=True)
    capa_verification_failures = Column(Integer, default=0)

    # Auditor close-out review — mirrors the same trio on permits_to_work and hazards.
    auditor_verified_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    auditor_verified_at = Column(DateTime, nullable=True)
    verification_notes = Column(Text, nullable=True)
