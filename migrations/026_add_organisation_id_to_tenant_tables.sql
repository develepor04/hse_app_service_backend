-- Migration: 026_add_organisation_id_to_tenant_tables
-- Adds organisation_id (tenant scoping) to validation_logs,
-- api_integrations, and documents so each org only sees its own data.

ALTER TABLE validation_logs
    ADD COLUMN organisation_id INT NULL AFTER id,
    ADD INDEX  idx_vlogs_org (organisation_id);

ALTER TABLE api_integrations
    ADD COLUMN organisation_id INT NULL AFTER id,
    ADD INDEX  idx_integrations_org (organisation_id);

ALTER TABLE documents
    ADD COLUMN organisation_id INT NULL AFTER id,
    ADD INDEX  idx_documents_org (organisation_id);
