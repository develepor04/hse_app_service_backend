"""Shared Worker→Supervisor→Manager workflow columns.

Incidents grew these columns first (migration 028); near misses, unsafe acts and risk
reports got the same set in migration 030. Keeping them in one mixin means the four
report types stay in step — a new workflow column is added here once, not four times.

`incident.py` predates this mixin and declares its columns inline; it is intentionally
left alone so the website's /incident-workflow endpoints keep their exact behaviour.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.mysql import JSON


class ReportWorkflowMixin:
    """Workflow state machine columns shared by every worker-submitted report type."""

    # ── State ────────────────────────────────────────────────────────────────
    # reported → acknowledged → under_investigation → (escalated | pending_approval) → closed
    workflow_status = Column(String(50), default="reported", index=True)
    severity = Column(String(50), default="medium")

    # ── Assignment & escalation ──────────────────────────────────────────────
    assigned_supervisor_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    escalated_to_manager_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    escalation_reason = Column(Text, nullable=True)

    # ── SLA timestamps ───────────────────────────────────────────────────────
    reported_at = Column(DateTime, nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    investigation_started_at = Column(DateTime, nullable=True)
    investigation_completed_at = Column(DateTime, nullable=True)
    escalated_at = Column(DateTime, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)

    # ── Supervisor investigation ─────────────────────────────────────────────
    root_cause = Column(String(255), nullable=True)
    five_why_analysis = Column(JSON, nullable=True)
    immediate_actions_taken = Column(Text, nullable=True)
    supervisor_signature = Column(String(255), nullable=True)

    # ── Manager closure ──────────────────────────────────────────────────────
    closure_notes = Column(Text, nullable=True)
    lessons_learned = Column(Text, nullable=True)
    manager_signature = Column(String(255), nullable=True)

    # ── Field evidence captured at report time ───────────────────────────────
    hazard_still_present = Column(String(10), nullable=True)
    witnesses_json = Column(JSON, nullable=True)
    evidence_json = Column(JSON, nullable=True)
    gps_latitude = Column(String(32), nullable=True)
    gps_longitude = Column(String(32), nullable=True)

    # ── Auditor verification (step 4 of the workflow chain, migration 044) ───
    # Independent assurance recorded against the original record. Never alters
    # workflow_status — the auditor observes the chain, they do not drive it.
    # ── Stage 02 ASSESS (migration 049) ───────────────────────────────────────
    # `severity` above is the reporter's impression and drives nothing.
    # `assessed_priority` is what the deterministic assessor produced and is the
    # field that ranks this record against every other event type — see
    # app.services.event_assessment.
    assessed_priority = Column(String(4), nullable=True)      # P1..P5
    assessed_label = Column(String(60), nullable=True)
    is_hipo = Column(Integer, default=0)
    is_recurring_pattern = Column(Integer, default=0)
    requires_systemic_rca = Column(Integer, default=0)
    response_due_at = Column(DateTime, nullable=True)
    min_investigator = Column(String(60), nullable=True)
    assessment_trace = Column(Text, nullable=True)
    assessed_at = Column(DateTime, nullable=True)

    # ── Stage 06 VERIFY · did the corrective action hold? (migration 057) ─────
    # The manager's in-workflow sign-off. Kept separate from the auditor trio
    # below, which is a post-closure review and gates nothing.
    capa_verified_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    capa_verified_at = Column(DateTime, nullable=True)
    capa_verification_notes = Column(Text, nullable=True)
    capa_verification_failures = Column(Integer, default=0)

    auditor_verified_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    auditor_verified_at = Column(DateTime, nullable=True)
    verification_result = Column(String(50), nullable=True)
    verification_notes = Column(Text, nullable=True)
