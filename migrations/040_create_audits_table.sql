-- ══════════════════════════════════════════════════════════════════════════════
-- 040 — Scheduled safety/compliance audits assigned to an auditor.
-- Mirrors app/models/audit.py (Audit) which was added without a matching migration.
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS audits (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id   INT          NULL,
    title             VARCHAR(200) NOT NULL,
    checklist_type    VARCHAR(120) NULL,
    site_id           INT          NULL,
    site_name         VARCHAR(200) NULL,
    department        VARCHAR(120) NULL,
    auditor_id        INT          NULL,
    scheduled_date    DATETIME     NULL,
    due_date          DATETIME     NULL,
    status            VARCHAR(20)  NOT NULL DEFAULT 'scheduled',
    priority          VARCHAR(10)  NOT NULL DEFAULT 'Med',
    progress          INT          NOT NULL DEFAULT 0,
    compliance_score  INT          NULL,
    findings_json     TEXT         NULL,
    submitted_at      DATETIME     NULL,
    created_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_audits_org (organisation_id),
    INDEX idx_audits_auditor (auditor_id),
    INDEX idx_audits_site (site_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
