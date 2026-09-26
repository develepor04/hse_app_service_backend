"""WF-07 · Safety Performance Score, plus the events its domains read.

    SPS = 0.25 x Hazard Exposure
        + 0.25 x Control Integrity
        + 0.20 x Work Discipline
        + 0.20 x Human Readiness
        + 0.10 x Org. Health

Weekly batch. Same five domains as PIRS, but SPS measures the current state —
it does not predict. PIRS is the AI counterpart.

Bands (higher = worse, it is a risk score):
    critical >=75 · high 50-74 · elevated 25-49 · acceptable 10-24 · low <10
"""
from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text

from app.models.aiisms_mixin import AiIsmsMetadataMixin
from app.models.base import Base


class SpsSnapshot(Base, AiIsmsMetadataMixin):
    __tablename__ = "sps_snapshots"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    scope = Column(String(20), nullable=False, default="org")

    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)

    hazard_exposure = Column(Numeric(6, 2), nullable=False, default=0)
    control_integrity = Column(Numeric(6, 2), nullable=False, default=0)
    work_discipline = Column(Numeric(6, 2), nullable=False, default=0)
    human_readiness = Column(Numeric(6, 2), nullable=False, default=0)
    org_health = Column(Numeric(6, 2), nullable=False, default=0)

    sps = Column(Numeric(6, 2), nullable=False, default=0)
    band = Column(String(20), nullable=False, default="low")

    # Data Quality Gate: sources >14 days stale are penalised 10 points and the
    # snapshot's confidence_score drops accordingly.
    data_completeness = Column(Numeric(5, 2), nullable=True)
    stale_data_penalty = Column(Numeric(5, 2), nullable=False, default=0)
    inputs = Column(JSON, nullable=True)
    computed_at = Column(DateTime, nullable=True)


class SpsAlert(Base, AiIsmsMetadataMixin):
    __tablename__ = "sps_alerts"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    sps_snapshot_id = Column(Integer, ForeignKey("sps_snapshots.id"), nullable=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)

    # delta | band_change | kpi_redline
    alert_type = Column(String(30), nullable=False, index=True)
    delta = Column(Numeric(6, 2), nullable=True)
    previous_band = Column(String(20), nullable=True)
    new_band = Column(String(20), nullable=True)
    severity = Column(String(20), nullable=True)
    message = Column(Text, nullable=True)
    # "2-3 pre-defined CAPAs per KPI" from the CAPA lookup table.
    suggested_capa = Column(JSON, nullable=True)

    acknowledged_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    capa_action_id = Column(Integer, ForeignKey("capa_actions.id"), nullable=True)


class CapaLookup(Base, AiIsmsMetadataMixin):
    __tablename__ = "capa_lookups"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    trigger_type = Column(String(40), nullable=False)
    trigger_key = Column(String(120), nullable=False)
    suggested_action = Column(Text, nullable=False)
    control_type = Column(String(40), nullable=True)
    default_due_days = Column(Integer, nullable=False, default=14)
    priority = Column(String(20), nullable=True)


class WorkExecutionEvent(Base, AiIsmsMetadataMixin):
    """Feeds the Work Discipline domain — permit bypass rate, closure quality."""

    __tablename__ = "work_execution_events"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    permit_id = Column(Integer, ForeignKey("permits_to_work.id"), nullable=True)
    event_type = Column(String(40), nullable=False, index=True)
    detail = Column(Text, nullable=True)
    occurred_at = Column(DateTime, nullable=True, index=True)


class SupervisorInteraction(Base, AiIsmsMetadataMixin):
    """Feeds the Organisational Health domain — supervisor safety engagement."""

    __tablename__ = "supervisor_interactions"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    supervisor_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    interaction_type = Column(String(40), nullable=False, index=True)
    detail = Column(Text, nullable=True)
    occurred_at = Column(DateTime, nullable=True)


class ChangeEvent(Base, AiIsmsMetadataMixin):
    """MOC-Lite change & drift log (C8) — procedure updates, equipment mods,
    staffing changes, temporary arrangements. Feeds the risk-spike input."""

    __tablename__ = "change_events"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    change_type = Column(String(40), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    risk_spike_score = Column(Numeric(6, 2), nullable=True)
    effective_from = Column(Date, nullable=True)
    effective_to = Column(Date, nullable=True)
    raised_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    reviewed_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    status = Column(String(30), nullable=False, default="open")
