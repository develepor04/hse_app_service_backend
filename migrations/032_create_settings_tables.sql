-- Migration: 032_create_settings_tables
-- Creates tables for: api_keys, webhooks (Settings page — API Keys / Webhooks tabs)
-- Adds: organisation.branding (logo/color customization, Settings page — Branding tab)

-- ── api_keys ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS api_keys (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id INT          NULL,
    name            VARCHAR(255) NOT NULL,
    key_prefix      VARCHAR(20)  NOT NULL,
    key_hash        VARCHAR(255) NOT NULL,
    scopes          VARCHAR(255) NOT NULL DEFAULT 'Read',
    is_active       TINYINT(1)   NOT NULL DEFAULT 1,
    created_by      VARCHAR(255) NULL,
    last_used_at    DATETIME     NULL,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_api_keys_org (organisation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── webhooks ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS webhooks (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id  INT          NULL,
    url              VARCHAR(500) NOT NULL,
    event_types      VARCHAR(255) NOT NULL DEFAULT '',
    secret           VARCHAR(255) NULL,
    is_active        TINYINT(1)   NOT NULL DEFAULT 1,
    last_triggered_at DATETIME    NULL,
    created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_webhooks_org (organisation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── organisation.branding ─────────────────────────────────────────────────────
ALTER TABLE organisation ADD COLUMN branding JSON NULL;
