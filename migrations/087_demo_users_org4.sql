-- Point the demo mobile logins at organisation 4 (WindTech Nacelle Manufacturing Ltd).
--
-- Why: org 4 holds the dataset the HSEIQ architecture diagram and
-- HSEIQ_KPI_Calculations.xlsx were built from — 73,220 shift records / 622,370
-- man-hours, 5,245 permits, 42 CAPA actions. Org 1 had incidents but almost no
-- shift hours, so every rate KPI (TRIR/LTIFR/LTISR/DART/FAR) divided by ~10 hours
-- and returned values ~86,000x too high.
--
-- app_roles is NOT org-scoped, so app_role_id is left alone and login roles
-- (operator / supervisor / auditor / safety_manager) are unaffected.
--
-- department_id and role_id ARE org-scoped and are remapped to org 4's
-- equivalents of the same names.
--
-- Rollback: migrations/087_demo_users_org4_ROLLBACK.sql

UPDATE users SET organisation_id = 4 WHERE id IN (15, 16, 17, 18);

-- Heavy Assembly: org1 dept 1 -> org4 dept 25
-- Production Operator: org1 role 11 -> org4 role 50
-- Department Supervisor: org1 role 4 -> org4 role 43
UPDATE employees SET organisation_id = 4, department_id = 25, role_id = 50 WHERE id = 601;  -- Worker One
UPDATE employees SET organisation_id = 4, department_id = 25, role_id = 43 WHERE id = 602;  -- Supervisor One
UPDATE employees SET organisation_id = 4 WHERE id IN (612, 625);                            -- Auditor One, Manager One
