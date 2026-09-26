from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.mysql import JSON
from app.models.base import Base


class CapaAction(Base):
    __tablename__ = "capa_actions"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    # Kept and still populated for incidents: fourteen aggregate queries filter
    # or join on it. New families use subject_family/subject_id below.
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=True)

    # Polymorphic parent (migration 056). Without this only incidents could
    # raise a corrective action, which is what made stages 05 IMPROVE and
    # 06 VERIFY unreachable for every other family.
    subject_family = Column(String(20), nullable=True)
    subject_id = Column(Integer, nullable=True)
    action_type = Column(String(100))
    description = Column(Text)
    root_cause_addressed = Column(String(255))
    responsible_person_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    due_date = Column(Date)
    status = Column(String(50))
    effectiveness_rating = Column(Integer)

    # ── WF-04 · priority matrix and due-date rules (migration 046) ────────────
    # priority_score/band answer "how important" (severity x systemic, 1-9).
    # capa_type answers "how fast" (P1 24h .. P5 90 days) and sets due_date.
    # The two are independent — see app.services.capa_priority.
    severity_potential = Column(Integer, nullable=True)   # 1-3
    systemic_risk = Column(Integer, nullable=True)        # 1-3
    priority_score = Column(Integer, nullable=True)       # 1-9
    priority_band = Column(String(20), nullable=True)     # Standard | High | Critical
    capa_type = Column(String(4), nullable=True)          # P1..P5
    capa_type_label = Column(String(20), nullable=True)
    target_hours = Column(Integer, nullable=True)
    evidence_required = Column(String(255), nullable=True)
    priority_explanation = Column(Text, nullable=True)

    # ── WF-04 · the ten-step lifecycle (migration 060) ────────────────────────
    # See app.services.capa_lifecycle for the rules these columns feed. The short
    # version: `Completed` no longer closes an action. Evidence is validated,
    # an independent reviewer confirms it, and the Safety Manager approves.
    capa_ref = Column(String(30), nullable=True)
    source = Column(String(30), nullable=True)
    raised_by = Column(Integer, nullable=True)

    # 03 PLAN. success_criteria is what the closure checks measure evidence
    # against; without it there is nothing to validate at step 08.
    action_plan = Column(Text, nullable=True)
    success_criteria = Column(Text, nullable=True)
    action_category = Column(String(30), nullable=True)
    hierarchy_level = Column(String(20), nullable=True)
    planned_at = Column(DateTime, nullable=True)
    plan_approved_by = Column(Integer, nullable=True)
    plan_approved_at = Column(DateTime, nullable=True)

    # 05 ASSIGN / 06 DO
    assigned_by = Column(Integer, nullable=True)
    assigned_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    interim_check_by = Column(Integer, nullable=True)
    interim_check_at = Column(DateTime, nullable=True)
    interim_check_notes = Column(Text, nullable=True)

    # 07 EVIDENCE / 08 VALIDATION
    evidence_submitted_at = Column(DateTime, nullable=True)
    evidence_submitted_by = Column(Integer, nullable=True)
    independent_review_by = Column(Integer, nullable=True)
    independent_review_at = Column(DateTime, nullable=True)
    independent_review_result = Column(String(20), nullable=True)
    independent_review_notes = Column(Text, nullable=True)
    closure_checks_json = Column(JSON, nullable=True)

    # 10 CLOSE
    closed_by = Column(Integer, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    closure_notes = Column(Text, nullable=True)
    lesson_learned = Column(Text, nullable=True)
    is_locked = Column(Integer, nullable=False, default=0)
    reopened_count = Column(Integer, nullable=False, default=0)

    # The escalation timer chain, weekly re-scoring, systemic flag.
    escalation_level = Column(Integer, nullable=False, default=0)
    last_escalated_at = Column(DateTime, nullable=True)
    last_rescored_at = Column(DateTime, nullable=True)
    systemic_flag = Column(Integer, nullable=False, default=0)
