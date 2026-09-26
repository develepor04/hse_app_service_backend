from sqlalchemy import JSON, Column, Date, DateTime, ForeignKey, Integer, String, Text
from app.models.base import Base


class Hazard(Base):
    __tablename__ = "hazards"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    category_id = Column(Integer, ForeignKey("hazard_categories.id"))
    hazard_name = Column(String(255), nullable=False)
    severity = Column(String(50))
    probability = Column(String(50))

    # The reporter's own answers, frozen at log time. `severity`, `probability`
    # and `controls` above are all overwritten by later stages — the assessor
    # rescores the first two, planning copies into the third — so these are the
    # only record of what the person who found the hazard actually said (073).
    reported_severity = Column(String(50), nullable=True)
    reported_probability = Column(String(50), nullable=True)
    existing_controls = Column(Text, nullable=True)
    reported_persons_exposed = Column(Integer, nullable=True)

    # ── The behavioural half (migration 080) ─────────────────────────────────
    # An unsafe act IS a hazard, so the two families merged and this table is
    # the survivor. These four are what the old `unsafe_acts` table carried and
    # this one did not: a physical condition has a severity and a control, a
    # behaviour has a person and a rule. Both halves live here now.
    act_type = Column(String(100), nullable=True)
    person_observed = Column(String(255), nullable=True)
    rule_violated = Column(String(255), nullable=True)
    corrective_advice_given = Column(String(10), nullable=True)
    # Traceability for the fold-in, and what makes 080 safe to re-run.
    merged_from_unsafe_act_id = Column(Integer, nullable=True)

    # ── Hazard register lifecycle (migration 031) ────────────────────────────
    # Additive: the website reads hazard_name/severity/probability as catalog data;
    # these columns let a worker log a field hazard and carry it through control.
    #
    # register_status carries all eight stages as of migration 066 — see
    # workflow_stages.HAZARD_REGISTER_STATUS_STAGE for the mapping:
    #   open → interim_control → under_review → controls_planned →
    #   pending_verification → controlled → closed
    register_status = Column(String(50), default="open")
    description = Column(Text, nullable=True)
    location_station_id = Column(Integer, ForeignKey("working_stations.id"), nullable=True)
    # The worker's own words for where it is, kept when what they typed matches
    # no station on record. Before this the text was simply dropped (072).
    location_other = Column(String(255), nullable=True)
    # The form's "It is still there" toggle. Null means nobody was asked, which
    # is not the same as the worker answering no.
    still_present = Column(Integer, nullable=True)
    logged_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    logged_at = Column(DateTime, nullable=True)
    reviewed_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_notes = Column(Text, nullable=True)
    controls = Column(Text, nullable=True)
    auditor_verified_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    auditor_verified_at = Column(DateTime, nullable=True)
    verification_notes = Column(Text, nullable=True)
    gps_latitude = Column(String(32), nullable=True)
    gps_longitude = Column(String(32), nullable=True)
    # Photos and video of the condition, as /uploads/ paths — the same column
    # name and shape the other four families use (076).
    evidence_json = Column(JSON, nullable=True)

    # ── Stage 02 ASSESS (migration 066) ──────────────────────────────────────
    # `severity` above is the reporter's impression and drives nothing.
    # `assessed_priority` is what ranks this hazard against every other event
    # family on the unified queue.
    assessed_priority = Column(String(4), nullable=True)      # P1..P5
    assessed_label = Column(String(60), nullable=True)
    risk_score = Column(Integer, nullable=True)               # severity × probability, 1-25
    assessed_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    assessed_at = Column(DateTime, nullable=True)
    response_due_at = Column(DateTime, nullable=True)

    # ── Stage 03 RESPOND ─────────────────────────────────────────────────────
    # Deliberately separate from `controls`, which holds the permanent measure.
    # One column for both would make "barriered off" indistinguishable from
    # "guard fitted".
    interim_control = Column(Text, nullable=True)
    interim_control_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    interim_control_at = Column(DateTime, nullable=True)
    work_stopped = Column(Integer, default=0)

    # ── Stage 04 INVESTIGATE ─────────────────────────────────────────────────
    review_started_at = Column(DateTime, nullable=True)
    root_cause = Column(String(255), nullable=True)
    persons_exposed = Column(Integer, nullable=True)

    # ── Stage 05 IMPROVE ─────────────────────────────────────────────────────
    planned_controls = Column(Text, nullable=True)
    control_hierarchy = Column(String(40), nullable=True)
    control_owner_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    control_due_date = Column(Date, nullable=True)
    controls_planned_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    controls_planned_at = Column(DateTime, nullable=True)

    # ── Stage 06 VERIFY ──────────────────────────────────────────────────────
    # The in-workflow check that the control held. Kept apart from the auditor
    # trio above, which is post-closure assurance and gates nothing.
    controls_verified_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    controls_verified_at = Column(DateTime, nullable=True)
    control_verification_notes = Column(Text, nullable=True)
    verification_failures = Column(Integer, default=0)

    # ── Stage 07 LEARN · 08 CLOSE ────────────────────────────────────────────
    lessons_learned = Column(Text, nullable=True)
    lesson_captured_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    lesson_captured_at = Column(DateTime, nullable=True)
    closure_notes = Column(Text, nullable=True)
    closed_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    closed_at = Column(DateTime, nullable=True)
