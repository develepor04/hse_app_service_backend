-- Migration: 026a_add_organisation_id_core_tables
-- Adds organisation_id to core entity tables for multi-tenancy.
-- Must run before 027 (backfill joins users.organisation_id).
-- Formerly the unnumbered add_organisation_id.sql (MySQL 8 does not support
-- ADD COLUMN IF NOT EXISTS — duplicates are skipped by run_migrations.py).

ALTER TABLE users
    ADD COLUMN organisation_id INT NULL,
    ADD INDEX idx_users_org (organisation_id),
    ADD CONSTRAINT fk_users_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

ALTER TABLE employees
    ADD COLUMN organisation_id INT NULL,
    ADD INDEX idx_employees_org (organisation_id),
    ADD CONSTRAINT fk_employees_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

ALTER TABLE sites
    ADD COLUMN organisation_id INT NULL,
    ADD INDEX idx_sites_org (organisation_id),
    ADD CONSTRAINT fk_sites_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

ALTER TABLE incidents
    ADD COLUMN organisation_id INT NULL,
    ADD INDEX idx_incidents_org (organisation_id),
    ADD CONSTRAINT fk_incidents_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

ALTER TABLE near_misses
    ADD COLUMN organisation_id INT NULL,
    ADD INDEX idx_near_misses_org (organisation_id),
    ADD CONSTRAINT fk_near_misses_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

ALTER TABLE capa_actions
    ADD COLUMN organisation_id INT NULL,
    ADD INDEX idx_capa_actions_org (organisation_id),
    ADD CONSTRAINT fk_capa_actions_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

ALTER TABLE safety_walks
    ADD COLUMN organisation_id INT NULL,
    ADD INDEX idx_safety_walks_org (organisation_id),
    ADD CONSTRAINT fk_safety_walks_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

ALTER TABLE permits_to_work
    ADD COLUMN organisation_id INT NULL,
    ADD INDEX idx_permits_to_work_org (organisation_id),
    ADD CONSTRAINT fk_permits_to_work_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

ALTER TABLE hazards
    ADD COLUMN organisation_id INT NULL,
    ADD INDEX idx_hazards_org (organisation_id),
    ADD CONSTRAINT fk_hazards_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

ALTER TABLE working_stations
    ADD COLUMN organisation_id INT NULL,
    ADD INDEX idx_working_stations_org (organisation_id),
    ADD CONSTRAINT fk_working_stations_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;
