-- Migration: Add organisation_id to all entity tables for multi-tenancy
-- Run this once on your MySQL database before restarting the backend.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS organisation_id INT NULL,
    ADD INDEX IF NOT EXISTS idx_users_org (organisation_id),
    ADD CONSTRAINT fk_users_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

ALTER TABLE employees
    ADD COLUMN IF NOT EXISTS organisation_id INT NULL,
    ADD INDEX IF NOT EXISTS idx_employees_org (organisation_id),
    ADD CONSTRAINT fk_employees_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

ALTER TABLE sites
    ADD COLUMN IF NOT EXISTS organisation_id INT NULL,
    ADD INDEX IF NOT EXISTS idx_sites_org (organisation_id),
    ADD CONSTRAINT fk_sites_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

ALTER TABLE incidents
    ADD COLUMN IF NOT EXISTS organisation_id INT NULL,
    ADD INDEX IF NOT EXISTS idx_incidents_org (organisation_id),
    ADD CONSTRAINT fk_incidents_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

ALTER TABLE near_misses
    ADD COLUMN IF NOT EXISTS organisation_id INT NULL,
    ADD INDEX IF NOT EXISTS idx_near_misses_org (organisation_id),
    ADD CONSTRAINT fk_near_misses_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

ALTER TABLE capa_actions
    ADD COLUMN IF NOT EXISTS organisation_id INT NULL,
    ADD INDEX IF NOT EXISTS idx_capa_actions_org (organisation_id),
    ADD CONSTRAINT fk_capa_actions_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

ALTER TABLE safety_walks
    ADD COLUMN IF NOT EXISTS organisation_id INT NULL,
    ADD INDEX IF NOT EXISTS idx_safety_walks_org (organisation_id),
    ADD CONSTRAINT fk_safety_walks_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

ALTER TABLE permits_to_work
    ADD COLUMN IF NOT EXISTS organisation_id INT NULL,
    ADD INDEX IF NOT EXISTS idx_permits_to_work_org (organisation_id),
    ADD CONSTRAINT fk_permits_to_work_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

ALTER TABLE hazards
    ADD COLUMN IF NOT EXISTS organisation_id INT NULL,
    ADD INDEX IF NOT EXISTS idx_hazards_org (organisation_id),
    ADD CONSTRAINT fk_hazards_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

ALTER TABLE working_stations
    ADD COLUMN IF NOT EXISTS organisation_id INT NULL,
    ADD INDEX IF NOT EXISTS idx_working_stations_org (organisation_id),
    ADD CONSTRAINT fk_working_stations_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

-- Assign existing test data to the first organisation (id=1) so it stays usable
-- Remove or change this if you want existing data to appear as "no org" (empty for all users).
-- UPDATE users SET organisation_id = 1 WHERE organisation_id IS NULL;
-- UPDATE employees SET organisation_id = 1 WHERE organisation_id IS NULL;
-- UPDATE incidents SET organisation_id = 1 WHERE organisation_id IS NULL;
-- UPDATE near_misses SET organisation_id = 1 WHERE organisation_id IS NULL;
-- UPDATE capa_actions SET organisation_id = 1 WHERE organisation_id IS NULL;
-- UPDATE safety_walks SET organisation_id = 1 WHERE organisation_id IS NULL;
-- UPDATE permits_to_work SET organisation_id = 1 WHERE organisation_id IS NULL;
-- UPDATE hazards SET organisation_id = 1 WHERE organisation_id IS NULL;
-- UPDATE working_stations SET organisation_id = 1 WHERE organisation_id IS NULL;
-- UPDATE sites SET organisation_id = 1 WHERE organisation_id IS NULL;
