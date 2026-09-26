-- Migration: 025_patch_data_imports_organisation_id
-- Adds organisation_id column to data_imports if it was created
-- by SQLAlchemy before migration 024 ran.

ALTER TABLE data_imports
    ADD COLUMN organisation_id INT NULL AFTER id,
    ADD INDEX  idx_data_imports_org (organisation_id);
