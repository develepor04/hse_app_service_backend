"""WF-13: Barrier/Bowtie Analysis Models

Bowtie analysis is a risk assessment method that visualizes:
- Threats (initiating events) on the left
- Top Event (major hazard) in the center  
- Consequences (outcomes) on the right
- Barriers (preventive and mitigative controls)

Source: ISO 31010:2019 Risk Assessment Techniques
"""
from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Integer,
    Numeric, String, Text, TIMESTAMP
)
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import relationship

from app.models.base import Base


class BowtieDiagram(Base):
    """Top-level bowtie diagram - represents one major accident hazard."""
    __tablename__ = "bowtie_diagrams"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=False, index=True)
    
    # Top Event (center of bowtie)
    top_event_name = Column(String(255), nullable=False)
    top_event_desc = Column(Text)
    
    # Classification
    hazard_category_id = Column(Integer, ForeignKey("hazard_categories.id"))
    site_id = Column(Integer, ForeignKey("sites.id"), index=True)
    process_unit = Column(String(255))
    
    # Risk ratings
    inherent_severity = Column(Integer)
    inherent_likelihood = Column(Integer)
    inherent_risk_score = Column(Integer)
    
    residual_severity = Column(Integer)
    residual_likelihood = Column(Integer)
    residual_risk_score = Column(Integer)
    
    target_severity = Column(Integer)
    target_likelihood = Column(Integer)
    target_risk_score = Column(Integer)
    
    # Metadata
    status = Column(String(50), default="active")
    review_frequency = Column(Integer, default=12)
    last_reviewed_at = Column(DateTime)
    next_review_due = Column(Date, index=True)
    owner_id = Column(Integer, ForeignKey("employees.id"))
    
    created_by = Column(Integer, ForeignKey("users.id"))
    
    # Relationships
    threats = relationship("BowtieThreat", back_populates="bowtie", cascade="all, delete-orphan")
    consequences = relationship("BowtieConsequence", back_populates="bowtie", cascade="all, delete-orphan")
    barriers = relationship("BowtieBarrier", back_populates="bowtie", cascade="all, delete-orphan")
    reviews = relationship("BowtieReview", back_populates="bowtie", cascade="all, delete-orphan")
    incident_links = relationship("BowtieIncidentLink", back_populates="bowtie", cascade="all, delete-orphan")


class BowtieThreat(Base):
    """Threat pathway - initiating event that could cause the top event (left side)."""
    __tablename__ = "bowtie_threats"

    bowtie_id = Column(Integer, ForeignKey("bowtie_diagrams.id"), nullable=False, index=True)
    
    threat_name = Column(String(255), nullable=False)
    threat_desc = Column(Text)
    threat_type = Column(String(100))
    
    base_likelihood = Column(Integer)
    display_order = Column(Integer, default=0)
    
    # Relationships
    bowtie = relationship("BowtieDiagram", back_populates="threats")
    barriers = relationship("BowtieBarrier", back_populates="threat", cascade="all, delete-orphan")


class BowtieConsequence(Base):
    """Consequence pathway - potential outcome after top event occurs (right side)."""
    __tablename__ = "bowtie_consequences"

    bowtie_id = Column(Integer, ForeignKey("bowtie_diagrams.id"), nullable=False, index=True)
    
    consequence_name = Column(String(255), nullable=False)
    consequence_desc = Column(Text)
    consequence_type = Column(String(100))
    
    max_severity = Column(Integer)
    max_fatalities = Column(Integer)
    max_injuries = Column(Integer)
    financial_impact = Column(Numeric(15, 2))
    environmental_impact = Column(Text)
    reputational_impact = Column(Text)
    
    display_order = Column(Integer, default=0)
    
    # Relationships
    bowtie = relationship("BowtieDiagram", back_populates="consequences")
    barriers = relationship("BowtieBarrier", back_populates="consequence", cascade="all, delete-orphan")


class BowtieBarrier(Base):
    """Control/defense that prevents threats or mitigates consequences."""
    __tablename__ = "bowtie_barriers"

    bowtie_id = Column(Integer, ForeignKey("bowtie_diagrams.id"), nullable=False, index=True)
    
    # Link to pathway
    threat_id = Column(Integer, ForeignKey("bowtie_threats.id"), index=True)
    consequence_id = Column(Integer, ForeignKey("bowtie_consequences.id"), index=True)
    barrier_side = Column(String(20), nullable=False)  # 'preventive' or 'mitigative'
    
    # Barrier details
    barrier_name = Column(String(255), nullable=False)
    barrier_desc = Column(Text)
    barrier_type = Column(String(100))
    
    # Classification
    control_type = Column(String(50))
    independence_level = Column(Integer)
    
    # Effectiveness
    design_effectiveness = Column(Integer)
    actual_effectiveness = Column(Integer)
    risk_reduction_factor = Column(Numeric(5, 2))
    
    # Verification
    verification_method = Column(String(100))
    verification_frequency = Column(Integer)
    last_verified_at = Column(DateTime)
    next_verification_due = Column(Date, index=True)
    
    # Performance standards
    performance_standard = Column(Text)
    failure_criteria = Column(Text)
    
    # Status
    status = Column(String(50), default="operational", index=True)
    degradation_reason = Column(Text)
    degraded_since = Column(DateTime)
    
    # Ownership
    owner_id = Column(Integer, ForeignKey("employees.id"))
    display_order = Column(Integer, default=0)
    
    # Relationships
    bowtie = relationship("BowtieDiagram", back_populates="barriers")
    threat = relationship("BowtieThreat", back_populates="barriers")
    consequence = relationship("BowtieConsequence", back_populates="barriers")
    verifications = relationship("BowtieBarrierVerification", back_populates="barrier", cascade="all, delete-orphan")
    alerts = relationship("BowtieBarrierAlert", back_populates="barrier", cascade="all, delete-orphan")


class BowtieBarrierVerification(Base):
    """Record of barrier inspection/test/verification."""
    __tablename__ = "bowtie_barrier_verifications"

    barrier_id = Column(Integer, ForeignKey("bowtie_barriers.id"), nullable=False, index=True)
    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=False, index=True)
    
    verification_date = Column(Date, nullable=False, index=True)
    verification_type = Column(String(100))
    verified_by = Column(Integer, ForeignKey("employees.id"))
    
    # Result
    result = Column(String(50), nullable=False, index=True)
    effectiveness_rating = Column(Integer)
    
    # Findings
    findings = Column(Text)
    deficiencies_found = Column(Text)
    
    # Actions
    corrective_actions = Column(Text)
    action_owner = Column(Integer, ForeignKey("employees.id"))
    action_due_date = Column(Date)
    action_completed = Column(Boolean, default=False)
    
    # Evidence
    evidence_photos = Column(JSON)
    evidence_docs = Column(JSON)
    
    next_verification_due = Column(Date)
    
    # Relationships
    barrier = relationship("BowtieBarrier", back_populates="verifications")


class BowtieIncidentLink(Base):
    """Link real incidents/near-misses to bowties to show which barriers failed."""
    __tablename__ = "bowtie_incident_links"

    bowtie_id = Column(Integer, ForeignKey("bowtie_diagrams.id"), nullable=False, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), index=True)
    near_miss_id = Column(Integer, ForeignKey("near_misses.id"), index=True)
    
    # What failed
    failed_barriers = Column(JSON)
    degraded_barriers = Column(JSON)
    threat_realized = Column(Integer)
    consequence_occurred = Column(Integer)
    
    # Analysis
    root_cause = Column(Text)
    lessons_learned = Column(Text)
    barriers_strengthened = Column(Text)
    
    linked_by = Column(Integer, ForeignKey("users.id"))
    linked_at = Column(TIMESTAMP)
    
    # Relationships
    bowtie = relationship("BowtieDiagram", back_populates="incident_links")


class BowtieReview(Base):
    """Formal review of a bowtie diagram."""
    __tablename__ = "bowtie_reviews"

    bowtie_id = Column(Integer, ForeignKey("bowtie_diagrams.id"), nullable=False, index=True)
    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=False, index=True)
    
    review_date = Column(Date, nullable=False, index=True)
    review_type = Column(String(100))
    reviewed_by = Column(Integer, ForeignKey("employees.id"))
    review_team = Column(JSON)
    
    # Findings
    bowtie_adequate = Column(Boolean)
    barriers_effective = Column(Boolean)
    gaps_identified = Column(Text)
    recommendations = Column(Text)
    
    # Changes made
    threats_added = Column(Integer, default=0)
    threats_removed = Column(Integer, default=0)
    consequences_added = Column(Integer, default=0)
    consequences_removed = Column(Integer, default=0)
    barriers_added = Column(Integer, default=0)
    barriers_removed = Column(Integer, default=0)
    
    # Risk re-assessment
    risk_changed = Column(Boolean, default=False)
    old_risk_score = Column(Integer)
    new_risk_score = Column(Integer)
    
    next_review_due = Column(Date)
    
    # Relationships
    bowtie = relationship("BowtieDiagram", back_populates="reviews")


class BowtieBarrierAlert(Base):
    """Alert when a barrier fails verification or becomes overdue."""
    __tablename__ = "bowtie_barrier_alerts"

    barrier_id = Column(Integer, ForeignKey("bowtie_barriers.id"), nullable=False, index=True)
    bowtie_id = Column(Integer, ForeignKey("bowtie_diagrams.id"), nullable=False, index=True)
    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=False, index=True)
    
    alert_type = Column(String(100), nullable=False)
    severity = Column(String(50), index=True)
    alert_message = Column(Text)
    triggered_at = Column(TIMESTAMP)
    
    # Assignment
    assigned_to = Column(Integer, ForeignKey("employees.id"))
    
    # Resolution
    resolved = Column(Boolean, default=False, index=True)
    resolved_at = Column(DateTime)
    resolved_by = Column(Integer, ForeignKey("employees.id"))
    resolution_notes = Column(Text)
    
    # Relationships
    barrier = relationship("BowtieBarrier", back_populates="alerts")
