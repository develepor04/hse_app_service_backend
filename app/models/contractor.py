"""WF-08 · Contractor & High-Risk Work.

    RAMS  = sum of 6 criteria x 0-20
            <60 reject · 60-79 conditional · >=80 approve
    LTIFR vs IOGP benchmark
            >2x benchmark = rejected · 1.5-2x conditional with enhanced monitoring

This registry is web-held master data. Mobile scores against it — the supervisor
scores RAMS on site, the auditor independently re-scores the same rubric.
"""
from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text

from app.models.aiisms_mixin import AiIsmsMetadataMixin
from app.models.base import Base


class ContractorCompany(Base, AiIsmsMetadataMixin):
    __tablename__ = "contractor_companies"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    company_name = Column(String(200), nullable=False)
    # Module 5 register fields — not needed by the mobile RAMS-scoring flow
    # above, but part of the client's own contractor-register KPI spec.
    service_type = Column(String(120), nullable=True)
    contract_start_date = Column(Date, nullable=True)
    contract_end_date = Column(Date, nullable=True)
    iso_45001_certified = Column(Integer, nullable=True)
    last_safety_audit_date = Column(Date, nullable=True)
    registration_no = Column(String(120), nullable=True)
    contact_name = Column(String(200), nullable=True)
    contact_email = Column(String(200), nullable=True)
    contact_phone = Column(String(60), nullable=True)

    # approved | conditional | barred | pending — gate 5 reads this
    prequalification_status = Column(String(20), nullable=False, default="pending", index=True)
    prequalified_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    prequalified_at = Column(DateTime, nullable=True)
    prequalification_notes = Column(Text, nullable=True)

    insurance_expiry = Column(Date, nullable=True)
    ssip_chas_status = Column(String(60), nullable=True)
    ssip_chas_expiry = Column(Date, nullable=True)
    ltifr_3yr = Column(Numeric(8, 3), nullable=True)
    trir_3yr = Column(Numeric(8, 3), nullable=True)

    approved_site_ids = Column(JSON, nullable=True)
    suspended = Column(Integer, nullable=False, default=0)
    suspended_reason = Column(Text, nullable=True)


class ContractorWorker(Base, AiIsmsMetadataMixin):
    __tablename__ = "contractor_workers"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    contractor_company_id = Column(
        Integer, ForeignKey("contractor_companies.id"), nullable=False, index=True
    )
    full_name = Column(String(200), nullable=False)
    badge_no = Column(String(120), nullable=True, index=True)
    trade = Column(String(120), nullable=True)
    induction_date = Column(Date, nullable=True)
    induction_valid_until = Column(Date, nullable=True)
    site_access_status = Column(String(20), nullable=False, default="pending")
    toolbox_completed_at = Column(DateTime, nullable=True)


class RamsScore(Base, AiIsmsMetadataMixin):
    __tablename__ = "rams_scores"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    contractor_company_id = Column(Integer, ForeignKey("contractor_companies.id"), nullable=True)
    permit_id = Column(Integer, ForeignKey("permits_to_work.id"), nullable=True)
    risk_report_id = Column(Integer, ForeignKey("risk_reports.id"), nullable=True)
    task_description = Column(Text, nullable=True)

    # Six criteria, 0-20 each.
    hazard_identification = Column(Integer, nullable=False, default=0)
    control_adequacy = Column(Integer, nullable=False, default=0)
    competence_evidence = Column(Integer, nullable=False, default=0)
    equipment_suitability = Column(Integer, nullable=False, default=0)
    emergency_arrangements = Column(Integer, nullable=False, default=0)
    supervision_arrangements = Column(Integer, nullable=False, default=0)

    total_score = Column(Integer, nullable=False, default=0)
    verdict = Column(String(20), nullable=False, default="reject")

    scored_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    scored_at = Column(DateTime, nullable=True)

    # "Independently re-score RAMS against the same rubric" — auditor screen.
    auditor_rescored_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    auditor_rescored_at = Column(DateTime, nullable=True)
    auditor_total_score = Column(Integer, nullable=True)
    auditor_notes = Column(Text, nullable=True)


class ContractorScorecard(Base, AiIsmsMetadataMixin):
    __tablename__ = "contractor_scorecards"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    contractor_company_id = Column(
        Integer, ForeignKey("contractor_companies.id"), nullable=False, index=True
    )
    period_year = Column(Integer, nullable=False)
    period_quarter = Column(Integer, nullable=False)

    score = Column(Numeric(6, 2), nullable=False, default=0)
    avg_rams_score = Column(Numeric(6, 2), nullable=True)
    incident_count = Column(Integer, nullable=False, default=0)
    permit_violations = Column(Integer, nullable=False, default=0)
    audit_findings = Column(Integer, nullable=False, default=0)
    ltifr = Column(Numeric(8, 3), nullable=True)

    # <50 enhanced oversight · <30 contract review · two quarters <30 = off list
    verdict = Column(String(30), nullable=False, default="ok")
    computed_at = Column(DateTime, nullable=True)


class ContractorHours(Base, AiIsmsMetadataMixin):
    """Real monthly hours-worked per contractor company — the denominator for
    Contractor TRIR (injuries x 200,000 / hours). The web Vendors page used to
    approximate this from PermitToWork durations; this is the actual figure."""

    __tablename__ = "contractor_hours"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    contractor_company_id = Column(
        Integer, ForeignKey("contractor_companies.id"), nullable=False, index=True
    )
    period_year = Column(Integer, nullable=False)
    period_month = Column(Integer, nullable=False)
    hours_worked = Column(Integer, nullable=False, default=0)


class IogpBenchmark(Base, AiIsmsMetadataMixin):
    __tablename__ = "iogp_benchmarks"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    benchmark_year = Column(Integer, nullable=False, index=True)
    region = Column(String(120), nullable=True)
    industry = Column(String(120), nullable=True)
    ltifr_benchmark = Column(Numeric(8, 3), nullable=False)
    trir_benchmark = Column(Numeric(8, 3), nullable=True)
