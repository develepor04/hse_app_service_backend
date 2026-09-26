"""WF-14: Process Safety Management (PSM) Models

PSM is a systematic framework for managing process hazards per:
- OSHA PSM 1910.119 (USA)
- API RP 750 (American Petroleum Institute)
- CCPS Guidelines (Center for Chemical Process Safety)

Core elements: PHA, MI, MOC, Operating Procedures, Training, etc.
"""
from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Integer,
    Numeric, String, Text, TIMESTAMP
)
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import relationship

from app.models.base import Base


class PSMElement(Base):
    """PSM program element - tracks implementation and compliance of each element."""
    __tablename__ = "psm_elements"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), index=True)
    
    # Element identification
    element_name = Column(String(255), nullable=False)
    element_code = Column(String(50))
    element_category = Column(String(100))
    regulatory_requirement = Column(Text)
    
    # Implementation status
    status = Column(String(50), default="not_started")
    implementation_date = Column(Date)
    compliance_level = Column(Integer)
    
    # Documentation
    procedures_documented = Column(Boolean, default=False)
    training_completed = Column(Boolean, default=False)
    audits_conducted = Column(Boolean, default=False)
    
    # Compliance tracking
    last_audit_date = Column(Date)
    next_audit_due = Column(Date, index=True)
    audit_findings_count = Column(Integer, default=0)
    open_actions = Column(Integer, default=0)
    
    # Ownership
    element_owner_id = Column(Integer, ForeignKey("employees.id"))
    created_by = Column(Integer, ForeignKey("users.id"))



class PHAStudy(Base):
    """Process Hazard Analysis study register."""
    __tablename__ = "psm_pha_studies"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    
    # Study identification
    study_name = Column(String(255), nullable=False)
    study_number = Column(String(100), unique=True, index=True)
    process_unit = Column(String(255))
    process_description = Column(Text)
    
    # PHA methodology
    pha_method = Column(String(100), nullable=False)
    study_scope = Column(Text)
    
    # Regulatory requirements
    regulatory_trigger = Column(String(255))
    revalidation_required = Column(Boolean, default=True)
    revalidation_years = Column(Integer, default=5)
    
    # Study status
    status = Column(String(50), default="planned", index=True)
    
    # Schedule
    planned_start_date = Column(Date)
    actual_start_date = Column(Date)
    planned_completion_date = Column(Date)
    actual_completion_date = Column(Date)
    last_revalidation_date = Column(Date)
    next_revalidation_due = Column(Date, index=True)
    
    # Team
    team_leader_id = Column(Integer, ForeignKey("employees.id"))
    facilitator_id = Column(Integer, ForeignKey("employees.id"))
    team_members = Column(JSON)
    
    # Results summary
    scenarios_analyzed = Column(Integer, default=0)
    recommendations_total = Column(Integer, default=0)
    recommendations_open = Column(Integer, default=0)
    high_risk_scenarios = Column(Integer, default=0)
    
    # Documentation
    report_file_path = Column(String(500))
    approval_status = Column(String(50), default="draft")
    approved_by = Column(Integer, ForeignKey("employees.id"))
    approved_at = Column(DateTime)
    
    created_by = Column(Integer, ForeignKey("users.id"))
    
    # Relationships
    scenarios = relationship("PHAScenario", back_populates="pha_study", cascade="all, delete-orphan")
    recommendations = relationship("PHARecommendation", back_populates="pha_study", cascade="all, delete-orphan")


class PHAScenario(Base):
    """Individual hazard scenario identified during PHA."""
    __tablename__ = "psm_pha_scenarios"

    pha_study_id = Column(Integer, ForeignKey("psm_pha_studies.id"), nullable=False, index=True)
    
    # Scenario details
    node_number = Column(String(50))
    scenario_number = Column(String(50))
    deviation = Column(String(255))
    cause = Column(Text)
    consequence = Column(Text)
    
    # Risk assessment
    likelihood_before = Column(Integer)
    severity_before = Column(Integer)
    risk_score_before = Column(Integer)
    
    # Existing safeguards
    safeguards = Column(Text)
    safeguards_adequate = Column(Boolean)
    
    likelihood_after = Column(Integer)
    severity_after = Column(Integer)
    risk_score_after = Column(Integer, index=True)
    
    # Risk tolerance
    risk_acceptable = Column(Boolean, default=False)
    requires_action = Column(Boolean, default=True)
    
    # Relationships
    pha_study = relationship("PHAStudy", back_populates="scenarios")



class PHARecommendation(Base):
    """PHA recommendation tracking."""
    __tablename__ = "psm_pha_recommendations"

    pha_study_id = Column(Integer, ForeignKey("psm_pha_studies.id"), nullable=False, index=True)
    scenario_id = Column(Integer, ForeignKey("psm_pha_scenarios.id"), index=True)
    
    # Recommendation details
    recommendation_number = Column(String(50))
    recommendation_text = Column(Text, nullable=False)
    recommendation_type = Column(String(100))
    priority = Column(String(50))
    
    # Assignment
    assigned_to = Column(Integer, ForeignKey("employees.id"), index=True)
    due_date = Column(Date, index=True)
    
    # Status
    status = Column(String(50), default="open", index=True)
    completion_date = Column(Date)
    completion_notes = Column(Text)
    verified_by = Column(Integer, ForeignKey("employees.id"))
    verified_at = Column(DateTime)
    
    # Cost tracking
    estimated_cost = Column(Numeric(15, 2))
    actual_cost = Column(Numeric(15, 2))
    
    # Relationships
    pha_study = relationship("PHAStudy", back_populates="recommendations")


class CriticalEquipment(Base):
    """Critical equipment register for Mechanical Integrity program."""
    __tablename__ = "psm_critical_equipment"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    
    # Equipment identification
    equipment_tag = Column(String(100), unique=True, nullable=False, index=True)
    equipment_name = Column(String(255), nullable=False)
    equipment_type = Column(String(100))
    process_unit = Column(String(255))
    
    # Classification
    is_safety_critical = Column(Boolean, default=False, index=True)
    criticality_level = Column(String(50))
    failure_consequence = Column(Text)
    
    # Design information
    design_pressure = Column(String(100))
    design_temperature = Column(String(100))
    material_of_construction = Column(String(255))
    manufacture_date = Column(Date)
    installation_date = Column(Date)
    design_life_years = Column(Integer)
    
    # Inspection requirements
    inspection_strategy = Column(String(100))
    inspection_frequency = Column(Integer)
    last_inspection_date = Column(Date)
    next_inspection_due = Column(Date, index=True)
    inspection_method = Column(String(255))
    
    # Testing requirements
    testing_frequency = Column(Integer)
    last_test_date = Column(Date)
    next_test_due = Column(Date, index=True)
    
    # Status
    equipment_status = Column(String(50), default="in_service")
    condition_rating = Column(Integer)
    deficiencies_open = Column(Integer, default=0)
    
    # Owner
    owner_id = Column(Integer, ForeignKey("employees.id"))
    created_by = Column(Integer, ForeignKey("users.id"))
    
    # Relationships
    inspections = relationship("EquipmentInspection", back_populates="equipment", cascade="all, delete-orphan")


class EquipmentInspection(Base):
    """Equipment inspection records for MI program."""
    __tablename__ = "psm_equipment_inspections"

    equipment_id = Column(Integer, ForeignKey("psm_critical_equipment.id"), nullable=False, index=True)
    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=False, index=True)
    
    # Inspection details
    inspection_date = Column(Date, nullable=False, index=True)
    inspection_type = Column(String(100))
    inspection_method = Column(String(255))
    inspector_id = Column(Integer, ForeignKey("employees.id"))
    inspector_cert_number = Column(String(100))
    
    # Results
    result = Column(String(50), nullable=False, index=True)
    condition_rating = Column(Integer)
    findings = Column(Text)
    deficiencies_found = Column(Text)
    
    # Corrective actions
    requires_repair = Column(Boolean, default=False)
    requires_replacement = Column(Boolean, default=False)
    action_required_by = Column(Date)
    action_completed = Column(Boolean, default=False)
    action_completion_date = Column(Date)
    
    # Next inspection
    next_inspection_due = Column(Date)
    
    # Documentation
    report_file_path = Column(String(500))
    photos = Column(JSON)
    
    # Relationships
    equipment = relationship("CriticalEquipment", back_populates="inspections")


class OperatingProcedure(Base):
    """PSM operating procedures register."""
    __tablename__ = "psm_operating_procedures"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), index=True)
    
    # Procedure identification
    procedure_number = Column(String(100), unique=True, index=True)
    procedure_title = Column(String(255), nullable=False)
    procedure_type = Column(String(100))
    process_unit = Column(String(255))
    
    # Content
    procedure_description = Column(Text)
    operating_limits = Column(Text)
    safety_considerations = Column(Text)
    equipment_required = Column(Text)
    
    # Version control
    version = Column(String(50), default="1.0")
    revision_number = Column(Integer, default=1)
    revision_reason = Column(Text)
    
    # Status
    status = Column(String(50), default="draft", index=True)
    effective_date = Column(Date)
    review_frequency = Column(Integer, default=24)
    last_review_date = Column(Date)
    next_review_due = Column(Date, index=True)
    
    # Ownership & approval
    author_id = Column(Integer, ForeignKey("employees.id"))
    reviewer_id = Column(Integer, ForeignKey("employees.id"))
    approver_id = Column(Integer, ForeignKey("employees.id"))
    approved_at = Column(DateTime)
    
    # Documentation
    document_file_path = Column(String(500))
    created_by = Column(Integer, ForeignKey("users.id"))


class PSMAudit(Base):
    """PSM compliance audit register."""
    __tablename__ = "psm_audits"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), index=True)
    
    # Audit identification
    audit_number = Column(String(100), unique=True, index=True)
    audit_name = Column(String(255), nullable=False)
    audit_type = Column(String(100))
    audit_scope = Column(Text)
    
    # Schedule
    planned_start_date = Column(Date)
    actual_start_date = Column(Date)
    planned_completion_date = Column(Date)
    actual_completion_date = Column(Date)
    
    # Team
    lead_auditor_id = Column(Integer, ForeignKey("employees.id"))
    audit_team = Column(JSON)
    
    # Results
    status = Column(String(50), default="planned", index=True)
    elements_audited = Column(Integer)
    findings_total = Column(Integer, default=0)
    findings_critical = Column(Integer, default=0)
    findings_major = Column(Integer, default=0)
    findings_minor = Column(Integer, default=0)
    observations = Column(Integer, default=0)
    
    # Compliance rating
    overall_compliance = Column(Integer)
    compliance_percentage = Column(Numeric(5, 2))
    
    # Documentation
    report_file_path = Column(String(500))
    created_by = Column(Integer, ForeignKey("users.id"))
    
    # Relationships
    findings = relationship("PSMAuditFinding", back_populates="audit", cascade="all, delete-orphan")


class PSMAuditFinding(Base):
    """PSM audit findings and corrective actions."""
    __tablename__ = "psm_audit_findings"

    audit_id = Column(Integer, ForeignKey("psm_audits.id"), nullable=False, index=True)
    psm_element_id = Column(Integer, ForeignKey("psm_elements.id"), index=True)
    
    # Finding details
    finding_number = Column(String(50))
    finding_type = Column(String(50), index=True)
    finding_description = Column(Text, nullable=False)
    requirement_reference = Column(String(255))
    
    # Evidence
    evidence = Column(Text)
    root_cause = Column(Text)
    
    # Corrective action
    corrective_action = Column(Text)
    assigned_to = Column(Integer, ForeignKey("employees.id"), index=True)
    due_date = Column(Date)
    
    # Status
    status = Column(String(50), default="open", index=True)
    completion_date = Column(Date)
    verified_by = Column(Integer, ForeignKey("employees.id"))
    verified_at = Column(DateTime)
    
    # Relationships
    audit = relationship("PSMAudit", back_populates="findings")
