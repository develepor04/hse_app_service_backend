"""WF-06 · Training, Competence & Human Readiness.

The competence matrix gates the permit: "Until the competence matrix exists on
web, the permit gate has nothing to check against." These models are the thing
gate 2 (Competence Verified) reads.
"""
from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text

from app.models.aiisms_mixin import AiIsmsMetadataMixin
from app.models.base import Base


class CertificationType(Base, AiIsmsMetadataMixin):
    __tablename__ = "certification_types"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    name = Column(String(200), nullable=False)
    code = Column(String(60), nullable=True)
    issuing_body = Column(String(200), nullable=True)
    validity_months = Column(Integer, nullable=True)
    # An expired safety-critical cert is a hard block, not a warning.
    is_safety_critical = Column(Integer, nullable=False, default=0)
    description = Column(Text, nullable=True)


class CompetenceProfile(Base, AiIsmsMetadataMixin):
    __tablename__ = "competence_profiles"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    name = Column(String(200), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=True)
    description = Column(Text, nullable=True)


class CompetenceMatrix(Base, AiIsmsMetadataMixin):
    __tablename__ = "competence_matrix"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    competence_profile_id = Column(Integer, ForeignKey("competence_profiles.id"), nullable=True)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=True)
    training_program_id = Column(Integer, ForeignKey("training_programs.id"), nullable=True)
    certification_type_id = Column(Integer, ForeignKey("certification_types.id"), nullable=True)
    requirement_name = Column(String(200), nullable=False)
    is_mandatory = Column(Integer, nullable=False, default=1)
    is_safety_critical = Column(Integer, nullable=False, default=0)
    validity_months = Column(Integer, nullable=True)
    # Which permit types this requirement gates. Empty/null = gates all of them.
    permit_types_gated = Column(JSON, nullable=True)


class TrainingRecord(Base, AiIsmsMetadataMixin):
    __tablename__ = "training_records"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    training_program_id = Column(Integer, ForeignKey("training_programs.id"), nullable=True)
    certification_type_id = Column(Integer, ForeignKey("certification_types.id"), nullable=True)
    competence_matrix_id = Column(Integer, ForeignKey("competence_matrix.id"), nullable=True)
    course_name = Column(String(200), nullable=True)
    completed_at = Column(Date, nullable=True)
    expires_at = Column(Date, nullable=True, index=True)
    score = Column(Numeric(6, 2), nullable=True)
    result = Column(String(20), nullable=True)  # pass | fail | pending
    certificate_ref = Column(String(200), nullable=True)
    evidence_photo = Column(Text, nullable=True)
    verified_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    verified_at = Column(DateTime, nullable=True)
    # Toolbox acknowledgement feeds the 80% attendance rule on the worker card.
    toolbox_acknowledged_at = Column(DateTime, nullable=True)


class CompetenceGap(Base, AiIsmsMetadataMixin):
    __tablename__ = "competence_gaps"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    competence_matrix_id = Column(Integer, ForeignKey("competence_matrix.id"), nullable=True)
    requirement_name = Column(String(200), nullable=True)
    # missing | expired | expiring_60 | expiring_30 | expiring_7
    gap_type = Column(String(30), nullable=False)
    is_safety_critical = Column(Integer, nullable=False, default=0)
    expires_at = Column(Date, nullable=True)
    detected_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    # "Assign buddy for new workers on WAH / CS / hot work."
    buddy_employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
