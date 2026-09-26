-- Link worker01 / supervisor01 to the employee records that actually carry the
-- organisation 4 operational history, so their personal dashboards render data.
--
-- IMPORTANT context: org 4's transaction rows (shift_schedule, incidents,
-- near_misses, permits_to_work, safety_walks) all reference employees 1-140, which
-- are stamped organisation_id = 1. Zero org-4 rows reference an actual org-4
-- employee (ids 451-625). So "point them at an org 4 employee" is not achievable
-- as stated — an org-4 employee has no history at all.
--
-- This is safe because the per-user queries filter the TRANSACTION table on
-- organisation_id (4, from the JWT) and join employees only by id — the employee
-- row's own organisation_id is never used. /employees/me likewise joins on
-- users.employee_id with no org filter.
--
-- Employee 21  (Henry Jackson) — 523 shifts / 4,445.5 hrs, 1 incident, 1 near miss, 2 CAPAs
-- Employee 103 (Oscar Cox)     — 4,005 supervised shifts / 34,042.5 team hrs, 130 permits issued
--
-- Known limitation: org 4's safety walks are logged by a disjoint set of employees
-- (20, 149, 68, 37, 101) who supervise no shifts, so supervisor01's walk metrics
-- still read zero. Reassigning walks would mutate the Excel-derived dataset.
--
-- Rollback: migrations/042_demo_link_org4_activity_ROLLBACK.sql

UPDATE users SET employee_id = 21  WHERE id = 15;  -- worker01     -> Henry Jackson
UPDATE users SET employee_id = 103 WHERE id = 16;  -- supervisor01 -> Oscar Cox
