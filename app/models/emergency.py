"""WF-15: Emergency Management Models

Emergency preparedness and response management per:
- NFPA 1600 (Standard on Continuity, Emergency, and Crisis Management)
- ICS/NIMS (Incident Command System / National Incident Management System)
- ISO 22320 (Emergency management — Requirements for incident response)
- OSHA Emergency Action Plans (29 CFR 1910.38)
"""
from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Integer,
    Numeric, String, Text, Time, TIMESTAMP
)
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import relationship

from app.models.base import Base


class EmergencyPlan(Base):
    """Master emergency response plan for different scenarios."""
    __tablename__ = "emergency_plans"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    
    # Plan identification
    plan_name = Column(String(255), nullable=False)
    plan_number = Column(String(100), unique=True, index=True)
    emergency_type = Column(String(100), nullable=False, index=True)
    scenario_description = Column(Text)
    
    # Scope & applicability
    applicable_sites = Column(JSON)
    applicable_areas = Column(Text)
    affected_population = Column(Integer)
    
    # Response objectives
    response_objectives = Column(Text)
    critical_actions = Column(Text)
    
    # Activation criteria
    activation_triggers = Column(Text)
    activation_authority = Column(String(255))
    
    # Status
    status = Column(String(50), default="draft", index=True)
    version = Column(String(50), default="1.0")
    
    # Review cycle
    review_frequency = Column(Integer, default=12)
    last_review_date = Column(Date)
    next_review_due = Column(Date, index=True)
    last_drill_date = Column(Date)
    
    # Ownership & approval
    plan_owner_id = Column(Integer, ForeignKey("employees.id"))
    approved_by = Column(Integer, ForeignKey("employees.id"))
    approved_at = Column(DateTime)
    effective_date = Column(Date)
    
    # Documentation
    document_file_path = Column(String(500))
    created_by = Column(Integer, ForeignKey("users.id"))
    
    # Relationships
    drills = relationship("EmergencyDrill", back_populates="plan", cascade="all, delete-orphan")
    activations = relationship("EmergencyActivation", back_populates="plan", cascade="all, delete-orphan")



class EmergencyResponseTeam(Base):
    """Emergency response team register (ICS-based structure)."""
    __tablename__ = "emergency_response_teams"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), index=True)
    
    # Team identification
    team_name = Column(String(255), nullable=False)
    team_type = Column(String(100), index=True)
    team_function = Column(Text)
    
    # ICS roles
    incident_commander_id = Column(Integer, ForeignKey("employees.id"))
    deputy_commander_id = Column(Integer, ForeignKey("employees.id"))
    team_members = Column(JSON)
    
    # Activation
    activation_level = Column(String(50))
    call_out_procedure = Column(Text)
    
    # Training requirements
    required_training = Column(Text)
    required_certifications = Column(Text)
    training_current = Column(Boolean, default=False)
    
    # Equipment
    assigned_equipment = Column(Text)
    equipment_location = Column(String(255))
    
    # Status
    status = Column(String(50), default="active", index=True)
    last_activation_date = Column(DateTime)
    last_drill_date = Column(Date)
    
    created_by = Column(Integer, ForeignKey("users.id"))


class EmergencyContact(Base):
    """Emergency notification list (internal & external)."""
    __tablename__ = "emergency_contacts"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), index=True)
    
    # Contact details
    contact_name = Column(String(255), nullable=False)
    contact_type = Column(String(100), nullable=False, index=True)
    organisation_name = Column(String(255))
    
    # Contact info
    primary_phone = Column(String(50), nullable=False)
    alternate_phone = Column(String(50))
    email = Column(String(255))
    address = Column(Text)
    
    # When to contact
    contact_priority = Column(Integer, default=1, index=True)
    emergency_types = Column(JSON)
    response_time_minutes = Column(Integer)
    
    # Availability
    available_24_7 = Column(Boolean, default=True)
    available_hours = Column(String(255))
    
    # Verification
    last_verified_date = Column(Date)
    next_verification_due = Column(Date)
    
    # Status
    status = Column(String(50), default="active", index=True)
    created_by = Column(Integer, ForeignKey("users.id"))


class EvacuationProcedure(Base):
    """Evacuation routes, assembly points, procedures."""
    __tablename__ = "evacuation_procedures"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    
    # Identification
    procedure_name = Column(String(255), nullable=False)
    building_area = Column(String(255), index=True)
    floor_level = Column(String(100))
    
    # Routes & assembly points
    primary_route = Column(Text)
    alternate_route = Column(Text)
    assembly_point_primary = Column(String(255), nullable=False)
    assembly_point_alternate = Column(String(255))
    assembly_point_gps = Column(String(100))
    
    # Evacuation details
    evacuation_method = Column(String(100))
    estimated_time_minutes = Column(Integer)
    max_occupancy = Column(Integer)
    
    # Special considerations
    vulnerable_persons = Column(Text)
    critical_equipment = Column(Text)
    hazardous_areas = Column(Text)
    
    # Signage & maps
    evacuation_map_path = Column(String(500))
    signage_adequate = Column(Boolean, default=True)
    lighting_adequate = Column(Boolean, default=True)
    
    # Status
    status = Column(String(50), default="active")
    last_reviewed_date = Column(Date)
    last_drill_date = Column(Date)
    
    created_by = Column(Integer, ForeignKey("users.id"))


class EmergencyDrill(Base):
    """Scheduled and executed emergency drills."""
    __tablename__ = "emergency_drills"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    emergency_plan_id = Column(Integer, ForeignKey("emergency_plans.id"), index=True)
    
    # Drill identification
    drill_name = Column(String(255), nullable=False)
    drill_type = Column(String(100), nullable=False)
    emergency_scenario = Column(String(255))
    
    # Schedule
    scheduled_date = Column(Date, nullable=False, index=True)
    scheduled_time = Column(Time)
    actual_date = Column(Date)
    actual_time = Column(Time)
    duration_minutes = Column(Integer)
    
    # Participants
    drill_coordinator_id = Column(Integer, ForeignKey("employees.id"))
    participants_planned = Column(Integer)
    participants_actual = Column(Integer)
    observers = Column(JSON)
    
    # Drill objectives
    objectives = Column(Text)
    success_criteria = Column(Text)
    
    # Results
    status = Column(String(50), default="scheduled", index=True)
    overall_rating = Column(Integer)
    objectives_met = Column(Boolean)
    
    # Performance metrics
    response_time_minutes = Column(Integer)
    evacuation_time_minutes = Column(Integer)
    headcount_accurate = Column(Boolean)
    communications_effective = Column(Boolean)
    equipment_functional = Column(Boolean)
    
    # Findings
    strengths_identified = Column(Text)
    weaknesses_identified = Column(Text)
    lessons_learned = Column(Text)
    corrective_actions = Column(Text)
    
    # Documentation
    report_file_path = Column(String(500))
    photos = Column(JSON)
    
    created_by = Column(Integer, ForeignKey("users.id"))
    
    # Relationships
    plan = relationship("EmergencyPlan", back_populates="drills")


class EmergencyEquipment(Base):
    """Emergency response equipment inventory."""
    __tablename__ = "emergency_equipment"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    
    # Equipment identification
    equipment_name = Column(String(255), nullable=False)
    equipment_type = Column(String(100), index=True)
    asset_tag = Column(String(100), unique=True, index=True)
    
    # Location
    building = Column(String(255))
    floor_level = Column(String(100))
    location_description = Column(Text)
    
    # Specifications
    capacity_size = Column(String(100))
    manufacturer = Column(String(255))
    model_number = Column(String(100))
    serial_number = Column(String(100))
    
    # Lifecycle
    installation_date = Column(Date)
    manufacture_date = Column(Date)
    expiry_date = Column(Date, index=True)
    
    # Inspection requirements
    inspection_frequency = Column(Integer)
    last_inspection_date = Column(Date)
    next_inspection_due = Column(Date, index=True)
    inspector_required = Column(String(255))
    
    # Status
    equipment_status = Column(String(50), default="operational", index=True)
    condition = Column(String(50))
    deficiencies = Column(Text)
    
    # Ownership
    responsible_person_id = Column(Integer, ForeignKey("employees.id"))
    created_by = Column(Integer, ForeignKey("users.id"))


class EmergencyActivation(Base):
    """Log of actual emergency activations and response."""
    __tablename__ = "emergency_activations"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    emergency_plan_id = Column(Integer, ForeignKey("emergency_plans.id"), index=True)
    
    # Emergency details
    emergency_type = Column(String(100), nullable=False)
    emergency_description = Column(Text, nullable=False)
    severity_level = Column(String(50), index=True)
    
    # Timeline
    occurred_at = Column(DateTime, nullable=False, index=True)
    detected_at = Column(DateTime)
    reported_at = Column(DateTime)
    response_initiated_at = Column(DateTime)
    under_control_at = Column(DateTime)
    all_clear_at = Column(DateTime)
    
    # Location
    location_description = Column(Text)
    affected_area = Column(String(255))
    
    # Response
    incident_commander_id = Column(Integer, ForeignKey("employees.id"))
    teams_activated = Column(JSON)
    external_agencies = Column(JSON)
    
    # Impact
    evacuated = Column(Boolean, default=False)
    people_evacuated = Column(Integer)
    injuries = Column(Integer, default=0)
    fatalities = Column(Integer, default=0)
    property_damage = Column(Numeric(15, 2))
    environmental_impact = Column(Text)
    business_interruption_hours = Column(Integer)
    
    # Response effectiveness
    plan_followed = Column(Boolean)
    plan_adequate = Column(Boolean)
    response_time_minutes = Column(Integer)
    evacuation_successful = Column(Boolean)
    communications_effective = Column(Boolean)
    
    # Post-emergency
    debriefing_conducted = Column(Boolean, default=False)
    debriefing_date = Column(Date)
    lessons_learned = Column(Text)
    plan_updates_required = Column(Text)
    
    # Investigation
    investigation_required = Column(Boolean, default=False)
    incident_id = Column(Integer, ForeignKey("incidents.id"))
    
    # Documentation
    report_file_path = Column(String(500))
    
    # Status
    status = Column(String(50), default="active", index=True)
    
    reported_by = Column(Integer, ForeignKey("users.id"))
    
    # Relationships
    plan = relationship("EmergencyPlan", back_populates="activations")
