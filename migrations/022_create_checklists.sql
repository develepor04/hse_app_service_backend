CREATE TABLE IF NOT EXISTS checklist_templates (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    checklist_type  VARCHAR(100) NOT NULL UNIQUE,
    display_name    VARCHAR(255) NOT NULL,
    submitter_roles TEXT NOT NULL,
    validator_roles TEXT NOT NULL,
    items_json      MEDIUMTEXT NOT NULL,
    ui_json         TEXT,
    sla_json        TEXT,
    is_active       TINYINT(1) NOT NULL DEFAULT 1,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS checklist_submissions (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    submission_uuid         VARCHAR(36) NOT NULL UNIQUE,
    checklist_type          VARCHAR(100) NOT NULL,
    site_id                 VARCHAR(50),
    zone_id                 VARCHAR(50),
    shift_name              VARCHAR(100),
    checklist_date          DATE NOT NULL,
    submitted_by_email      VARCHAR(255) NOT NULL DEFAULT '',
    submitted_by_role       VARCHAR(100) NOT NULL DEFAULT '',
    status                  ENUM('draft','submitted','validated','rejected') NOT NULL DEFAULT 'draft',
    submit_due_at           DATETIME,
    validate_due_at         DATETIME,
    submit_sla_breached     TINYINT(1) NOT NULL DEFAULT 0,
    validate_sla_breached   TINYINT(1) NOT NULL DEFAULT 0,
    validation_decision     VARCHAR(50),
    validation_notes        TEXT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_cs_type   (checklist_type),
    INDEX idx_cs_status (status),
    INDEX idx_cs_date   (checklist_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS checklist_submission_items (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    submission_uuid VARCHAR(36) NOT NULL,
    item_no         INT NOT NULL,
    section_name    VARCHAR(255) NOT NULL,
    item_text       TEXT NOT NULL,
    is_required     TINYINT(1) NOT NULL DEFAULT 0,
    response_value  VARCHAR(50),
    remark          TEXT,
    evidence_json   TEXT,
    updated_by_email VARCHAR(255),
    updated_by_role  VARCHAR(100),
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_sub_item (submission_uuid, item_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS checklist_logs (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    submission_uuid VARCHAR(36) NOT NULL,
    action_type     VARCHAR(100) NOT NULL,
    actor_email     VARCHAR(255) NOT NULL DEFAULT '',
    actor_role      VARCHAR(100) NOT NULL DEFAULT '',
    from_status     VARCHAR(50),
    to_status       VARCHAR(50),
    notes           TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_cl_uuid (submission_uuid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
