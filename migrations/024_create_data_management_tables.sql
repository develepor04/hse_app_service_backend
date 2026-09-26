-- Migration: 024_create_data_management_tables
-- Creates tables for: data_imports, validation_logs, api_integrations,
--                     documents, equipment_certifications

-- ── data_imports ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS data_imports (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id INT NULL,
    file_name       VARCHAR(255) NOT NULL,
    import_type     VARCHAR(50)  NOT NULL DEFAULT 'excel',
    data_type       VARCHAR(100) NOT NULL,
    records_total   INT          NOT NULL DEFAULT 0,
    records_success INT          NOT NULL DEFAULT 0,
    records_failed  INT          NOT NULL DEFAULT 0,
    status          VARCHAR(50)  NOT NULL DEFAULT 'success',
    uploaded_by     VARCHAR(255) NOT NULL DEFAULT 'Admin',
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_data_imports_org (organisation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── validation_logs ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS validation_logs (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    file_name        VARCHAR(255) NOT NULL,
    rule             VARCHAR(255) NOT NULL,
    status           VARCHAR(50)  NOT NULL DEFAULT 'pass',
    records_affected INT          NOT NULL DEFAULT 0,
    message          TEXT         NULL,
    timestamp        VARCHAR(50)  NULL,
    created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_validation_logs_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── api_integrations ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS api_integrations (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    name           VARCHAR(255) NOT NULL,
    type           VARCHAR(100) NOT NULL,
    endpoint_url   VARCHAR(500) NULL,
    auth_type      VARCHAR(50)  NOT NULL DEFAULT 'api_key',
    is_active      TINYINT(1)   NOT NULL DEFAULT 1,
    sync_frequency VARCHAR(50)  NOT NULL DEFAULT 'realtime',
    description    TEXT         NULL,
    last_sync      VARCHAR(50)  NULL,
    created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_api_integrations_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── documents ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS documents (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    file_name   VARCHAR(255) NOT NULL,
    file_type   VARCHAR(20)  NOT NULL,
    category    VARCHAR(20)  NOT NULL DEFAULT 'pdf',
    record_type VARCHAR(100) NULL,
    size        VARCHAR(30)  NULL,
    uploaded_by VARCHAR(255) NOT NULL DEFAULT 'Admin',
    file_path   TEXT         NULL,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_documents_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── equipment_certifications ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS equipment_certifications (
    id                   INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id      INT          NULL,
    equipment_name       VARCHAR(255) NOT NULL,
    equipment_type       VARCHAR(100) NULL,
    site_id              INT          NULL,
    zone                 VARCHAR(100) NULL,
    serial_number        VARCHAR(100) NULL,
    manufacturer         VARCHAR(255) NULL,
    model                VARCHAR(100) NULL,
    certification_type   VARCHAR(100) NULL,
    certified_by         VARCHAR(255) NULL,
    issue_date           DATE         NULL,
    expiry_date          DATE         NULL,
    next_inspection_date DATE         NULL,
    compliance_standard  VARCHAR(100) NULL,
    created_at           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_equip_cert_org  (organisation_id),
    INDEX idx_equip_cert_site (site_id),
    CONSTRAINT fk_equip_cert_org
        FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL,
    CONSTRAINT fk_equip_cert_site
        FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
