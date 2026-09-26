-- Migration: 062_audit_wf05
-- WF-05 Audit, Inspection & Compliance Monitoring — Schedule to Verified Closure
-- Source: EHSERA-ISMS-AO-2026-v1.0, ALGO-ISMS-WF-2026-v1.0, AUD-FORM-01, Rev 5.0
--
-- What existed before this: an audit was a title, an auditor, a JSON blob of
-- checklist lines and a status. The auditor answered pass/fail/na and the system
-- divided passes by answers to get a percentage. That is one of the ten steps.
--
-- Missing entirely: the risk-band-driven programme that decides how often a site
-- is audited, the brief pack, the opening and closing meetings, the five finding
-- classifications, the 2/1/0 point rubric that replaces the pass ratio, the score
-- bands, the overall rating, the two signatures that gate report issue, and the
-- close-out tracking that keeps an audit open until every action it raised has
-- been verified.
--
-- Everything here is additive. `findings_json`, `compliance_score` and `status`
-- keep their meaning, so the web Compliance section and the KPI queries that read
-- them are untouched.

-- ── Steps 01-02 PLAN · what triggered this audit, and who is on the team ─────
-- trigger_type is the six-way column of the "what starts an audit" table. It is
-- not cosmetic: "audit not conducted" escalates against the scheduled date, and
-- an unscheduled inspection raised by a risk spike carries no notice period,
-- which is the one case where the two weeks' notice rule does not apply.
ALTER TABLE audits
    ADD COLUMN audit_ref VARCHAR(30) NULL COMMENT 'AUD-000123, generated at creation',
    ADD COLUMN trigger_type VARCHAR(30) NULL
        COMMENT 'scheduled_programme | post_incident | management_directed | regulatory | score_threshold | risk_spike',
    ADD COLUMN audit_scope VARCHAR(30) NULL COMMENT 'inspection | full_audit | re_audit',
    ADD COLUMN risk_band VARCHAR(12) NULL COMMENT 'Site band at scheduling: critical | high | medium | low',
    ADD COLUMN site_score DECIMAL(6,2) NULL COMMENT 'Safety performance score the band came from',
    ADD COLUMN audit_team_json TEXT NULL COMMENT 'Safety officers supporting the lead auditor',
    ADD COLUMN auditee_manager_id INT NULL COMMENT 'Site supervisor / department head being audited',
    ADD COLUMN auditee_notified_at DATETIME NULL COMMENT 'Two weeks minimum, except unannounced',
    ADD COLUMN team_assigned_at DATETIME NULL,
    ADD COLUMN assigned_by INT NULL COMMENT 'Safety Manager who named the lead and team';

-- ── Step 03 PREPARE · the auto-generated brief pack ─────────────────────────
-- Built seven days before by the system, not by the auditor: previous findings,
-- open corrective actions, current score and overdue permits. Stored rather than
-- computed on read so the pack is readable offline and so the audit records what
-- the auditor was actually told, not what the data looks like today.
ALTER TABLE audits
    ADD COLUMN brief_pack_json MEDIUMTEXT NULL COMMENT 'Snapshot the auditor prepared from',
    ADD COLUMN brief_pack_generated_at DATETIME NULL,
    ADD COLUMN brief_pack_reviewed_at DATETIME NULL COMMENT 'Lead auditor confirms they read it';

-- ── Steps 04 and 08 · the two meetings ──────────────────────────────────────
-- The opening meeting is a structured record, not a note: scope, method and
-- sampling approach are agreed jointly so there is no dispute afterwards about
-- what was in or out of scope. The closing meeting is where the auditee confirms
-- factual accuracy, and after it the findings lock.
ALTER TABLE audits
    ADD COLUMN opening_meeting_json TEXT NULL COMMENT 'scope | method | sampling | attendees',
    ADD COLUMN opening_meeting_at DATETIME NULL,
    ADD COLUMN closing_meeting_json TEXT NULL COMMENT 'attendees | notes | agreed timeframes',
    ADD COLUMN closing_meeting_at DATETIME NULL,
    ADD COLUMN auditee_confirmed_at DATETIME NULL COMMENT 'Factual accuracy agreed',
    ADD COLUMN auditee_signature MEDIUMTEXT NULL COMMENT 'On-device signature, data URI or stored path',
    ADD COLUMN auditee_signed_name VARCHAR(160) NULL,
    ADD COLUMN findings_locked_at DATETIME NULL
        COMMENT 'After the closing meeting findings change only by formal amendment';

-- ── Step 07 CLASSIFY · the point rubric and the bands ───────────────────────
-- The pass ratio is replaced by (points earned / points possible) x 100 with
-- full = 2, partial = 1, non-compliance = 0 and Not Applicable excluded from the
-- denominator, so a score is never diluted by questions that did not apply.
ALTER TABLE audits
    ADD COLUMN points_earned INT NULL,
    ADD COLUMN points_possible INT NULL,
    ADD COLUMN score_band VARCHAR(16) NULL COMMENT 'excellent | good | acceptable | poor',
    ADD COLUMN overall_rating VARCHAR(24) NULL
        COMMENT 'satisfactory | requires_improvement | unsatisfactory — set by finding counts, not by score',
    ADD COLUMN section_scores_json TEXT NULL COMMENT 'Per-section percentages, drives the auto Minor NC',
    ADD COLUMN classified_at DATETIME NULL;

-- ── Step 09 REPORT · the signature that gates distribution ──────────────────
-- "The report cannot be issued without the Lead Auditor's signature." Signing is
-- what triggers distribution and creates the corrective actions, so the two are
-- recorded on the same row and neither can happen without the other.
-- The Safety Manager reviews and approves the report before wider distribution,
-- and the Admin owns distribution beyond the site. Two separate stamps because
-- they are two different people answering two different questions: is this
-- report sound, and who outside this site should see it.
ALTER TABLE audits
    ADD COLUMN auditor_signature MEDIUMTEXT NULL,
    ADD COLUMN auditor_signed_name VARCHAR(160) NULL,
    ADD COLUMN report_ref VARCHAR(40) NULL,
    ADD COLUMN report_issued_at DATETIME NULL,
    ADD COLUMN report_distributed_to TEXT NULL COMMENT 'Employee ids notified on issue',
    ADD COLUMN report_approved_by INT NULL COMMENT 'Safety Manager — gates wider distribution',
    ADD COLUMN report_approved_at DATETIME NULL,
    ADD COLUMN report_approval_notes TEXT NULL;

-- ── Step 10 CLOSE · re-audit triggers and the link to the previous audit ────
-- gps_latitude and gps_longitude are deliberately absent: migration 044 already
-- added them to this table. Naming them here would make MySQL reject the whole
-- ALTER as a duplicate column, taking the other five with it, because an ALTER
-- either applies in full or not at all.
ALTER TABLE audits
    ADD COLUMN previous_audit_id INT NULL COMMENT 'Same site and type — drives the repeat-finding flag',
    ADD COLUMN re_audit_required TINYINT(1) NOT NULL DEFAULT 0,
    ADD COLUMN re_audit_reason VARCHAR(160) NULL,
    ADD COLUMN re_audit_due_date DATE NULL,
    ADD COLUMN closed_at DATETIME NULL;

CREATE INDEX idx_audits_ref ON audits (audit_ref);
CREATE INDEX idx_audits_site_sched ON audits (site_id, scheduled_date);

-- ── The checklist, promoted out of the JSON blob ────────────────────────────
-- Sections matter now: a section falling below 60% raises a Minor NC on its own,
-- and a JSON array with no section column cannot express that. Per-item rows
-- also give evidence something to hang off and let step 05 log one answer at a
-- time, which is what "logged live on the mobile app, no paper" requires.
CREATE TABLE IF NOT EXISTS audit_checklist_items (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    organisation_id     INT NULL,
    audit_id            INT NOT NULL,
    seq                 INT NOT NULL DEFAULT 0,
    section             VARCHAR(120) NULL COMMENT 'Groups items for the section percentage',
    title               VARCHAR(255) NOT NULL,
    question            TEXT NULL,
    clause              VARCHAR(60) NULL COMMENT 'ISO 45001 / 14001 clause the item maps to',
    is_critical         TINYINT(1) NOT NULL DEFAULT 0
        COMMENT 'Scoring zero here is an automatic Major NC and alerts immediately',
    response            VARCHAR(16) NULL COMMENT 'full | partial | none | na',
    points_earned       INT NULL,
    points_possible     INT NULL,
    remarks             TEXT NULL,
    classification      VARCHAR(20) NULL
        COMMENT 'conformance | observation | minor_nc | major_nc | critical',
    evidence_count      INT NOT NULL DEFAULT 0,
    gps_latitude        DECIMAL(10,7) NULL,
    gps_longitude       DECIMAL(10,7) NULL,
    answered_at         DATETIME NULL,
    answered_by         INT NULL,
    KEY idx_aci_audit (audit_id),
    KEY idx_aci_org (organisation_id),
    CONSTRAINT fk_aci_audit FOREIGN KEY (audit_id) REFERENCES audits (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Findings · the classified output of the audit ───────────────────────────
-- One row per finding, because a finding is tracked out individually and carries
-- its own corrective action, its own deadline and its own repeat flag. A
-- conformance is recorded too: "audits record what is working, not only what is
-- wrong", and without the positive rows the score has no numerator to explain.
CREATE TABLE IF NOT EXISTS audit_findings (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    organisation_id         INT NULL,
    audit_id                INT NOT NULL,
    checklist_item_id       INT NULL,
    finding_ref             VARCHAR(40) NULL,
    section                 VARCHAR(120) NULL,
    title                   VARCHAR(255) NOT NULL,
    description             TEXT NULL,
    clause                  VARCHAR(60) NULL,
    classification          VARCHAR(20) NOT NULL
        COMMENT 'conformance | observation | minor_nc | major_nc | critical',
    classified_by           INT NULL COMMENT 'The lead auditor owns the judgement',
    auto_classified         TINYINT(1) NOT NULL DEFAULT 0
        COMMENT 'Set when a threshold raised it rather than a person',
    is_repeat               TINYINT(1) NOT NULL DEFAULT 0
        COMMENT 'Same finding in either of the last two audits — treated as more serious',
    repeat_of_audit_id      INT NULL,
    corrective_action_due   DATE NULL COMMENT 'Agreed at the closing meeting',
    capa_id                 INT NULL COMMENT 'The action raised for this finding',
    status                  VARCHAR(20) NOT NULL DEFAULT 'open'
        COMMENT 'open | action_raised | actioned | verified | closed',
    verified_at             DATETIME NULL,
    verified_by             INT NULL,
    verification_notes      TEXT NULL,
    closed_at               DATETIME NULL,
    gps_latitude            DECIMAL(10,7) NULL,
    gps_longitude           DECIMAL(10,7) NULL,
    KEY idx_af_audit (audit_id),
    KEY idx_af_org_class (organisation_id, classification),
    KEY idx_af_status (status),
    CONSTRAINT fk_af_audit FOREIGN KEY (audit_id) REFERENCES audits (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Evidence · attached to the checklist line, never to a general folder ─────
-- "Photos attached to the specific checklist item, not dumped in a general
-- folder." GPS and captured_at are on the row because the defensibility claim is
-- that the observation was made at that place at that time.
CREATE TABLE IF NOT EXISTS audit_evidence (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    organisation_id     INT NULL,
    audit_id            INT NOT NULL,
    checklist_item_id   INT NULL,
    finding_id          INT NULL,
    kind                VARCHAR(20) NOT NULL DEFAULT 'photo'
        COMMENT 'photo | document | note | scan | interview',
    file_url            VARCHAR(500) NULL,
    caption             TEXT NULL,
    scanned_ref         VARCHAR(120) NULL COMMENT 'QR / barcode payload — asset, permit or vehicle id',
    -- A worker interview is evidence like any other. "What the worker actually
    -- does is the evidence, not what the procedure says", so the answer is
    -- recorded against the person who gave it and against the checklist line it
    -- proves, rather than as a loose note.
    subject_employee_id INT NULL COMMENT 'Worker interviewed or observed',
    subject_name        VARCHAR(160) NULL,
    interview_prompt    VARCHAR(255) NULL COMMENT 'What they were asked to explain or demonstrate',
    competence_verified TINYINT(1) NULL COMMENT 'Competence card checked against the matrix',
    gps_latitude        DECIMAL(10,7) NULL,
    gps_longitude       DECIMAL(10,7) NULL,
    captured_at         DATETIME NULL,
    captured_by         INT NULL,
    KEY idx_ae_audit (audit_id),
    KEY idx_ae_item (checklist_item_id),
    KEY idx_ae_finding (finding_id),
    CONSTRAINT fk_ae_audit FOREIGN KEY (audit_id) REFERENCES audits (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── The programme · how often each site gets audited, and why ───────────────
-- "Audits are not booked by hand. The system generates the annual programme from
-- each site's risk band, and that band is driven by the site's own safety
-- performance score. A site that deteriorates gets audited more often,
-- automatically."
CREATE TABLE IF NOT EXISTS audit_programme (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    organisation_id         INT NULL,
    site_id                 INT NULL,
    site_name               VARCHAR(200) NULL,
    risk_band               VARCHAR(12) NOT NULL DEFAULT 'low',
    site_score              DECIMAL(6,2) NULL,
    inspection_frequency    VARCHAR(30) NULL COMMENT 'monthly | quarterly | bi_annual',
    audit_frequency         VARCHAR(30) NULL COMMENT 'quarterly | bi_annual | annual',
    last_inspection_at      DATETIME NULL,
    last_audit_at           DATETIME NULL,
    next_inspection_due     DATE NULL,
    next_audit_due          DATE NULL,
    re_audit_trigger        VARCHAR(200) NULL,
    band_changed_at         DATETIME NULL,
    computed_at             DATETIME NULL,
    UNIQUE KEY uq_programme_site (organisation_id, site_id),
    KEY idx_programme_band (risk_band)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Legacy audits keep working. Give them a reference and mark them as scheduled
-- programme work so the trigger column is never blank on an existing row.
UPDATE audits
   SET audit_ref = CONCAT('AUD-', LPAD(id, 6, '0'))
 WHERE audit_ref IS NULL;

UPDATE audits
   SET trigger_type = 'scheduled_programme'
 WHERE trigger_type IS NULL;

UPDATE audits
   SET audit_scope = 'full_audit'
 WHERE audit_scope IS NULL;
