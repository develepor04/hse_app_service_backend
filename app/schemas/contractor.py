"""Schemas for WF-08 · Contractor & High-Risk Work."""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ContractorCompanyCreate(BaseModel):
    company_name: str = Field(..., min_length=1)
    registration_no: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    insurance_expiry: Optional[date] = None
    ssip_chas_status: Optional[str] = None
    ssip_chas_expiry: Optional[date] = None
    ltifr_3yr: Optional[float] = None
    trir_3yr: Optional[float] = None
    approved_site_ids: Optional[List[int]] = None
    # Module 5 register fields — same columns the Excel importer's
    # _insert_contractor_companies fills from SD_ContractorRegister, exposed
    # here too so Manual Entry can capture the same register in full.
    service_type: Optional[str] = None
    contract_start_date: Optional[date] = None
    contract_end_date: Optional[date] = None
    prequalification_status: Optional[str] = Field(None, pattern="^(approved|conditional|barred|pending)$")
    iso_45001_certified: Optional[bool] = None
    last_safety_audit_date: Optional[date] = None
    suspended: Optional[bool] = None


class ContractorCompanyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_name: str
    registration_no: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    prequalification_status: str
    prequalified_at: Optional[datetime] = None
    prequalification_notes: Optional[str] = None
    insurance_expiry: Optional[date] = None
    ssip_chas_status: Optional[str] = None
    ssip_chas_expiry: Optional[date] = None
    ltifr_3yr: Optional[float] = None
    trir_3yr: Optional[float] = None
    approved_site_ids: Optional[List[int]] = None
    suspended: int = 0
    suspended_reason: Optional[str] = None


class PrequalifyRequest(BaseModel):
    """Safety Manager pre-qualifies. LTIFR is judged against the IOGP benchmark:
    >2x = reject, 1.5-2x = conditional with enhanced monitoring."""

    status: Optional[str] = Field(None, pattern="^(approved|conditional|barred|pending)$")
    notes: Optional[str] = None
    approved_site_ids: Optional[List[int]] = None
    benchmark_year: Optional[int] = None


class PrequalifyResponse(BaseModel):
    contractor_company_id: int
    company_name: str
    status: str
    ltifr_ratio: Optional[float] = None
    ltifr_verdict: str
    benchmark_ltifr: Optional[float] = None
    explanation: str


class SuspendRequest(BaseModel):
    suspended: bool = True
    reason: Optional[str] = None


class ContractorWorkerCreate(BaseModel):
    contractor_company_id: int
    full_name: str = Field(..., min_length=1)
    badge_no: Optional[str] = None
    trade: Optional[str] = None
    induction_date: Optional[date] = None
    induction_valid_until: Optional[date] = None


class ContractorWorkerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contractor_company_id: int
    full_name: str
    badge_no: Optional[str] = None
    trade: Optional[str] = None
    induction_date: Optional[date] = None
    induction_valid_until: Optional[date] = None
    site_access_status: str
    toolbox_completed_at: Optional[datetime] = None


class SiteAccessUpdate(BaseModel):
    site_access_status: str = Field(..., pattern="^(granted|revoked|pending)$")
    toolbox_completed: bool = False


class RamsScoreCreate(BaseModel):
    """Six criteria, 0-20 each. <60 reject · 60-79 conditional · >=80 approve."""

    contractor_company_id: Optional[int] = None
    permit_id: Optional[int] = None
    risk_report_id: Optional[int] = None
    task_description: Optional[str] = None
    hazard_identification: int = Field(0, ge=0, le=20)
    control_adequacy: int = Field(0, ge=0, le=20)
    competence_evidence: int = Field(0, ge=0, le=20)
    equipment_suitability: int = Field(0, ge=0, le=20)
    emergency_arrangements: int = Field(0, ge=0, le=20)
    supervision_arrangements: int = Field(0, ge=0, le=20)


class RamsScoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contractor_company_id: Optional[int] = None
    permit_id: Optional[int] = None
    task_description: Optional[str] = None
    hazard_identification: int
    control_adequacy: int
    competence_evidence: int
    equipment_suitability: int
    emergency_arrangements: int
    supervision_arrangements: int
    total_score: int
    verdict: str
    scored_by: Optional[int] = None
    scored_at: Optional[datetime] = None
    auditor_total_score: Optional[int] = None
    auditor_rescored_at: Optional[datetime] = None
    auditor_notes: Optional[str] = None


class RamsRescore(BaseModel):
    """Auditor independently re-scores against the same rubric."""

    hazard_identification: int = Field(0, ge=0, le=20)
    control_adequacy: int = Field(0, ge=0, le=20)
    competence_evidence: int = Field(0, ge=0, le=20)
    equipment_suitability: int = Field(0, ge=0, le=20)
    emergency_arrangements: int = Field(0, ge=0, le=20)
    supervision_arrangements: int = Field(0, ge=0, le=20)
    notes: Optional[str] = None


class ScorecardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contractor_company_id: int
    period_year: int
    period_quarter: int
    score: float
    avg_rams_score: Optional[float] = None
    incident_count: int
    permit_violations: int
    audit_findings: int
    ltifr: Optional[float] = None
    verdict: str
    computed_at: Optional[datetime] = None


class ContractorHoursCreate(BaseModel):
    contractor_company_id: int
    period_year: int
    period_month: int = Field(..., ge=1, le=12)
    hours_worked: int = Field(0, ge=0)


class ContractorHoursResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contractor_company_id: int
    period_year: int
    period_month: int
    hours_worked: int


class IogpBenchmarkCreate(BaseModel):
    benchmark_year: int
    ltifr_benchmark: float
    trir_benchmark: Optional[float] = None
    region: Optional[str] = None
    industry: Optional[str] = None
