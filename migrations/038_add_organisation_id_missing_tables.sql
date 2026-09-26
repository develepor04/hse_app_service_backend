-- Migration: 038_add_organisation_id_missing_tables
-- Adds organisation_id (tenant scoping) to tables whose ORM models/services
-- already assume the column but no prior numbered migration created it:
-- hazard_categories, roles, permit_types, training_programs, policies,
-- departments, shift_schedule.

ALTER TABLE hazard_categories
    ADD COLUMN organisation_id INT NULL AFTER id,
    ADD INDEX  idx_hazard_categories_org (organisation_id),
    ADD CONSTRAINT fk_hazard_categories_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

ALTER TABLE roles
    ADD COLUMN organisation_id INT NULL AFTER id,
    ADD INDEX  idx_roles_org (organisation_id),
    ADD CONSTRAINT fk_roles_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

ALTER TABLE permit_types
    ADD COLUMN organisation_id INT NULL AFTER id,
    ADD INDEX  idx_permit_types_org (organisation_id),
    ADD CONSTRAINT fk_permit_types_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

ALTER TABLE training_programs
    ADD COLUMN organisation_id INT NULL AFTER id,
    ADD INDEX  idx_training_programs_org (organisation_id),
    ADD CONSTRAINT fk_training_programs_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

ALTER TABLE policies
    ADD COLUMN organisation_id INT NULL AFTER id,
    ADD INDEX  idx_policies_org (organisation_id),
    ADD CONSTRAINT fk_policies_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

ALTER TABLE departments
    ADD COLUMN organisation_id INT NULL AFTER id,
    ADD INDEX  idx_departments_org (organisation_id),
    ADD CONSTRAINT fk_departments_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;

ALTER TABLE shift_schedule
    ADD COLUMN organisation_id INT NULL AFTER id,
    ADD INDEX  idx_shift_schedule_org (organisation_id),
    ADD CONSTRAINT fk_shift_schedule_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL;
