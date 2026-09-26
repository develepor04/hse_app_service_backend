"""WF-05 Audit, Inspection & Compliance Monitoring — the ORM side.

Rev 5.0 of the workflow runs ten steps from a system-generated schedule to a
verified closure. The tables here carry the parts of that which cannot live in a
JSON blob: the checklist as rows (so a section can score on its own), the
findings as rows (so each is tracked out individually) and the evidence as rows
(so a photo belongs to a checklist line rather than to a folder).
"""
from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text,
)
from app.models.base import Base


class Audit(Base):
    """A scheduled audit or inspection, from the programme through to closure.

    Org-scoped and assigned to a lead auditor. The submitted result feeds the web
    Compliance section (audit readiness) exactly like the other roles' mobile
    submissions — `status`, `compliance_score` and `findings_json` keep the
    meanings the existing dashboards already read.
    """
    __tablename__ = "audits"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    audit_ref = Column(String(30))                     # AUD-000123
    title = Column(String(200), nullable=False)
    checklist_type = Column(String(120))
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    site_name = Column(String(200))          # denormalised label for the mobile card
    department = Column(String(120))
    shift = Column(String(20), nullable=True)  # Morning | Afternoon | Night
    auditor_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    scheduled_date = Column(DateTime)
    due_date = Column(DateTime)
    status = Column(String(20), default="scheduled")
    priority = Column(String(10), default="Med")        # High | Med | Low
    progress = Column(Integer, default=0)               # 0-100
    compliance_score = Column(Integer)                  # 0-100, the rubric percentage
    findings_json = Column(Text)                        # legacy checklist blob
    submitted_at = Column(DateTime)

    # ── 01-02 PLAN ──────────────────────────────────────────────────────────
    trigger_type = Column(String(30))       # see audit_programme.TRIGGERS
    audit_scope = Column(String(30))        # inspection | full_audit | re_audit
    risk_band = Column(String(12))          # critical | high | medium | low
    site_score = Column(Numeric(6, 2))
    audit_team_json = Column(Text)
    auditee_manager_id = Column(Integer)
    auditee_notified_at = Column(DateTime)
    team_assigned_at = Column(DateTime)
    assigned_by = Column(Integer)

    # ── 03 PREPARE ──────────────────────────────────────────────────────────
    brief_pack_json = Column(Text)
    brief_pack_generated_at = Column(DateTime)
    brief_pack_reviewed_at = Column(DateTime)

    # ── 04 / 08 the two meetings ────────────────────────────────────────────
    opening_meeting_json = Column(Text)
    opening_meeting_at = Column(DateTime)
    closing_meeting_json = Column(Text)
    closing_meeting_at = Column(DateTime)
    auditee_confirmed_at = Column(DateTime)
    auditee_signature = Column(Text)
    auditee_signed_name = Column(String(160))
    findings_locked_at = Column(DateTime)

    # ── 07 CLASSIFY ─────────────────────────────────────────────────────────
    points_earned = Column(Integer)
    points_possible = Column(Integer)
    score_band = Column(String(16))         # excellent | good | acceptable | poor
    overall_rating = Column(String(24))     # satisfactory | requires_improvement | unsatisfactory
    section_scores_json = Column(Text)
    classified_at = Column(DateTime)

    # ── 09 REPORT ───────────────────────────────────────────────────────────
    auditor_signature = Column(Text)
    auditor_signed_name = Column(String(160))
    report_ref = Column(String(40))
    report_issued_at = Column(DateTime)
    report_distributed_to = Column(Text)
    # The Safety Manager reviews and approves before the report goes wider than
    # the site. Separate from the auditor's signature: one says the audit is
    # sound, the other says it is finished.
    report_approved_by = Column(Integer)
    report_approved_at = Column(DateTime)
    report_approval_notes = Column(Text)

    # ── 10 CLOSE ────────────────────────────────────────────────────────────
    previous_audit_id = Column(Integer)
    re_audit_required = Column(Boolean, default=False)
    re_audit_reason = Column(String(160))
    re_audit_due_date = Column(Date)
    # The trigger fires automatically; what to do about it is the Safety
    # Manager's judgement — schedule it, or waive it with a reason.
    re_audit_decision = Column(String(20))       # pending | scheduled | waived
    re_audit_decided_by = Column(Integer)
    re_audit_decided_at = Column(DateTime)
    re_audit_decision_note = Column(Text)
    re_audit_audit_id = Column(Integer)

    # Wider release, owned by the Admin. Distinct from the issue-time
    # distribution to the site — and gated on the Safety Manager's approval.
    distributed_beyond_site_at = Column(DateTime)
    distributed_beyond_site_by = Column(Integer)
    distribution_scope = Column(String(30))      # site | organisation | external
    distribution_recipients = Column(Text)

    reminder_sent_at = Column(DateTime)
    generated_by_programme = Column(Boolean, default=False)
    template_id = Column(Integer)
    gps_latitude = Column(Numeric(10, 7))
    gps_longitude = Column(Numeric(10, 7))
    closed_at = Column(DateTime)


class AuditChecklistItem(Base):
    """One line of the checklist, answered on the phone as the auditor walks.

    `section` is load-bearing rather than decorative: a section scoring below 60%
    raises a Minor NC on its own, which a flat list of questions cannot express.
    """
    __tablename__ = "audit_checklist_items"

    organisation_id = Column(Integer, nullable=True, index=True)
    audit_id = Column(Integer, ForeignKey("audits.id", ondelete="CASCADE"), nullable=False, index=True)
    seq = Column(Integer, default=0)
    section = Column(String(120))
    title = Column(String(255), nullable=False)
    question = Column(Text)
    clause = Column(String(60))
    # Scoring zero on a critical item is an automatic Major NC and alerts the
    # Safety Manager instantly — work may be suspended on the spot.
    is_critical = Column(Boolean, default=False)
    response = Column(String(16))           # full | partial | none | na
    points_earned = Column(Integer)
    points_possible = Column(Integer)
    remarks = Column(Text)
    classification = Column(String(20))
    evidence_count = Column(Integer, default=0)
    gps_latitude = Column(Numeric(10, 7))
    gps_longitude = Column(Numeric(10, 7))
    answered_at = Column(DateTime)
    answered_by = Column(Integer)


class AuditFinding(Base):
    """A classified finding, tracked out on its own.

    Conformances are stored alongside the non-conformances. An audit that only
    records what is wrong cannot show what is working, and the score has no
    numerator to explain.
    """
    __tablename__ = "audit_findings"

    organisation_id = Column(Integer, nullable=True, index=True)
    audit_id = Column(Integer, ForeignKey("audits.id", ondelete="CASCADE"), nullable=False, index=True)
    checklist_item_id = Column(Integer)
    finding_ref = Column(String(40))
    section = Column(String(120))
    title = Column(String(255), nullable=False)
    description = Column(Text)
    clause = Column(String(60))
    classification = Column(String(20), nullable=False)
    classified_by = Column(Integer)
    auto_classified = Column(Boolean, default=False)
    is_repeat = Column(Boolean, default=False)
    repeat_of_audit_id = Column(Integer)
    corrective_action_due = Column(Date)
    capa_id = Column(Integer)
    status = Column(String(20), default="open")
    verified_at = Column(DateTime)
    verified_by = Column(Integer)
    verification_notes = Column(Text)
    closed_at = Column(DateTime)
    gps_latitude = Column(Numeric(10, 7))
    gps_longitude = Column(Numeric(10, 7))


class AuditEvidence(Base):
    """A photo, document, scan or note bound to the checklist line it proves."""
    __tablename__ = "audit_evidence"

    organisation_id = Column(Integer, nullable=True, index=True)
    audit_id = Column(Integer, ForeignKey("audits.id", ondelete="CASCADE"), nullable=False, index=True)
    checklist_item_id = Column(Integer, index=True)
    finding_id = Column(Integer, index=True)
    # photo | video | document | note | scan | interview
    #
    # `video` is not new storage — media_storage has accepted the video content
    # types all along and the audit upload path allows them — it is the value
    # that says so, without which a recording was filed as a `photo` and every
    # renderer put it in an <img>.
    kind = Column(String(20), default="photo")
    file_url = Column(String(500))
    caption = Column(Text)
    scanned_ref = Column(String(120))            # QR / barcode payload
    # A worker interview is evidence like any other — what the worker actually
    # does is the evidence, not what the procedure says.
    subject_employee_id = Column(Integer)
    subject_name = Column(String(160))
    interview_prompt = Column(String(255))
    competence_verified = Column(Boolean)
    gps_latitude = Column(Numeric(10, 7))
    gps_longitude = Column(Numeric(10, 7))
    captured_at = Column(DateTime)
    captured_by = Column(Integer)


class AuditProgramme(Base):
    """The annual calendar for one site, regenerated from its risk band.

    Not booked by hand: the band comes from the site's safety performance score,
    so a site that deteriorates is audited more often without anyone deciding to.
    """
    __tablename__ = "audit_programme"

    organisation_id = Column(Integer, nullable=True, index=True)
    site_id = Column(Integer)
    site_name = Column(String(200))
    risk_band = Column(String(12), default="low")
    site_score = Column(Numeric(6, 2))
    inspection_frequency = Column(String(30))
    audit_frequency = Column(String(30))
    last_inspection_at = Column(DateTime)
    last_audit_at = Column(DateTime)
    next_inspection_due = Column(Date)
    next_audit_due = Column(Date)
    re_audit_trigger = Column(String(200))
    band_changed_at = Column(DateTime)
    computed_at = Column(DateTime)

    # Computed is not the same as authorised. The Safety Manager authorises the
    # programme for their site; the Admin approves the calendar across all of
    # them. Neither implies the other, so they are two stamps rather than one.
    programme_year = Column(Integer)
    authorised_by = Column(Integer)
    authorised_at = Column(DateTime)
    authorisation_note = Column(Text)
    approved_by = Column(Integer)
    approved_at = Column(DateTime)
    generated_at = Column(DateTime)
    generated_count = Column(Integer, default=0)
    scope_concerns = Column(Text)


class AuditChecklistTemplate(Base):
    """What every audit runs from, maintained by the Admin on the web console.

    Versioned rather than edited in place: an audit conducted last quarter was
    run against the template as it stood then, and rewriting it underneath would
    falsify the record of what was actually asked.
    """
    __tablename__ = "audit_checklist_templates"

    organisation_id = Column(Integer, nullable=True, index=True)
    name = Column(String(200), nullable=False)
    checklist_type = Column(String(120))
    description = Column(Text)
    standard = Column(String(60))
    version = Column(Integer, default=1)
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)
    created_by = Column(Integer)
    updated_by = Column(Integer)


class AuditChecklistTemplateItem(Base):
    """One question on a template."""
    __tablename__ = "audit_checklist_template_items"

    template_id = Column(
        Integer, ForeignKey("audit_checklist_templates.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    seq = Column(Integer, default=0)
    section = Column(String(120))
    title = Column(String(255), nullable=False)
    question = Column(Text)
    clause = Column(String(60))
    is_critical = Column(Boolean, default=False)
