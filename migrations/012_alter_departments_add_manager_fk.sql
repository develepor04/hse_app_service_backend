-- Migration: 012_alter_departments_add_manager_fk
-- Adds the manager_id FK on departments now that the employees table exists.
-- This resolves the circular dependency: departments <-> employees.

ALTER TABLE departments
    ADD CONSTRAINT fk_departments_manager
        FOREIGN KEY (manager_id) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE;
