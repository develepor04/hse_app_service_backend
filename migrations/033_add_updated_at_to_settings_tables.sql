-- Migration: 033_add_updated_at_to_settings_tables
-- app/models/base.py's Base class declares updated_at on every model — the
-- api_keys/webhooks tables created in 029 were missing it.

ALTER TABLE api_keys
    ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP;

ALTER TABLE webhooks
    ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP;
