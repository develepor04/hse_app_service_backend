-- Migration: 065_audit_wf05_web
-- WF-05 · the parts of the workflow that live on the web console.
--
-- 062-064 built everything the auditor does in the field. This builds what the
-- Safety Manager and the Admin do before and after the visit — and the machinery
-- behind it, which is mostly missing rather than merely unexposed:
--
--   · the annual programme is computed but nobody authorises it
--   · nothing generates the year's audits from a site's band — audits are made
--     one at a time by hand, which is exactly what "audits are not booked by
--     hand" says must not happen
--   · checklist templates are hardcoded Python dicts, so the Admin cannot
--     maintain the thing every audit runs from
--   · the re-audit trigger fires automatically and no human can decide on it,
--     though the Safety Manager is supposed to own that decision
--   · distribution beyond the site has an owner but no mechanism

-- ── Checklist templates · what the Admin maintains ──────────────────────────
-- One row per template, its items in the child table. Versioned rather than
-- edited in place: an audit conducted last quarter was run against the template
-- as it stood then, and silently rewriting it would falsify the record of what
-- was actually asked.
CREATE TABLE IF NOT EXISTS audit_checklist_templates (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    organisation_id     INT NULL,
    name                VARCHAR(200) NOT NULL,
    checklist_type      VARCHAR(120) NULL COMMENT 'Matched against an audit checklist_type when seeding',
    description         TEXT NULL,
    standard            VARCHAR(60) NULL COMMENT 'ISO 45001 | ISO 14001 | OSHA VPP',
    version             INT NOT NULL DEFAULT 1,
    is_active           TINYINT(1) NOT NULL DEFAULT 1,
    is_default          TINYINT(1) NOT NULL DEFAULT 0
        COMMENT 'Used when no template matches the audit type',
    created_by          INT NULL,
    updated_by          INT NULL,
    KEY idx_act_org (organisation_id),
    KEY idx_act_type (checklist_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS audit_checklist_template_items (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    template_id         INT NOT NULL,
    seq                 INT NOT NULL DEFAULT 0,
    section             VARCHAR(120) NULL,
    title               VARCHAR(255) NOT NULL,
    question            TEXT NULL,
    clause              VARCHAR(60) NULL,
    is_critical         TINYINT(1) NOT NULL DEFAULT 0
        COMMENT 'Scoring zero here is an automatic Major NC and alerts immediately',
    KEY idx_acti_template (template_id),
    CONSTRAINT fk_acti_template FOREIGN KEY (template_id)
        REFERENCES audit_checklist_templates (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── The programme · authorised by a person, not merely computed ─────────────
-- Two separate stamps because they are two different decisions. The Safety
-- Manager authorises the programme for their site; the Admin approves the
-- calendar across all sites. Neither implies the other.
ALTER TABLE audit_programme
    ADD COLUMN programme_year INT NULL,
    ADD COLUMN authorised_by INT NULL COMMENT 'Safety Manager — authorises for this site',
    ADD COLUMN authorised_at DATETIME NULL,
    ADD COLUMN authorisation_note TEXT NULL,
    ADD COLUMN approved_by INT NULL COMMENT 'Admin — approves the calendar across all sites',
    ADD COLUMN approved_at DATETIME NULL,
    ADD COLUMN generated_at DATETIME NULL COMMENT 'When the year was last generated from this band',
    ADD COLUMN generated_count INT NOT NULL DEFAULT 0,
    ADD COLUMN scope_concerns TEXT NULL
        COMMENT 'Safety Manager flags a specific concern to include in scope';

-- ── The re-audit decision · the Safety Manager owns it ──────────────────────
-- The trigger fires automatically and sets re_audit_required. What happens next
-- is a judgement: schedule it, or waive it with a reason. Without these columns
-- the flag could only ever be true, so a site that had already been re-audited
-- kept reading as owing one.
ALTER TABLE audits
    ADD COLUMN re_audit_decision VARCHAR(20) NULL COMMENT 'pending | scheduled | waived',
    ADD COLUMN re_audit_decided_by INT NULL,
    ADD COLUMN re_audit_decided_at DATETIME NULL,
    ADD COLUMN re_audit_decision_note TEXT NULL,
    ADD COLUMN re_audit_audit_id INT NULL COMMENT 'The audit raised to satisfy the re-audit';

-- ── Distribution beyond the site · the Admin owns it ────────────────────────
-- Distinct from the issue-time distribution already on the row. Issuing sends
-- the report to the site and its Safety Manager; this is the wider release, and
-- it cannot happen before the Safety Manager has approved.
ALTER TABLE audits
    ADD COLUMN distributed_beyond_site_at DATETIME NULL,
    ADD COLUMN distributed_beyond_site_by INT NULL,
    ADD COLUMN distribution_scope VARCHAR(30) NULL COMMENT 'site | organisation | external',
    ADD COLUMN distribution_recipients TEXT NULL;

-- ── The 14-day reminder · "sets a reminder 14 days out" ────────────────────
-- Stamped so the scheduler sends it once. A reminder that re-sends every sweep
-- teaches people to ignore the channel, which is worse than no reminder.
ALTER TABLE audits
    ADD COLUMN reminder_sent_at DATETIME NULL,
    ADD COLUMN generated_by_programme TINYINT(1) NOT NULL DEFAULT 0
        COMMENT 'Created by the calendar generator rather than by hand',
    ADD COLUMN template_id INT NULL COMMENT 'The template version this audit was seeded from';

CREATE INDEX idx_audits_reminder ON audits (scheduled_date, reminder_sent_at);
