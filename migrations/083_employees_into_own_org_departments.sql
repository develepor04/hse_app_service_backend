-- ─────────────────────────────────────────────────────────────────────────────
-- 083 · Put every employee in a department belonging to their own organisation
--
-- Same class of bug 082 fixed for departments->sites, one level down. Employees
-- in organisations 2, 3 and 4 all carried department_id values owned by
-- organisation 1:
--
--     emp_org=2  dept_org=1  150 rows
--     emp_org=3  dept_org=1  150 rows
--     emp_org=4  dept_org=1  150 rows
--     emp_org=4  dept_org=4    4 rows   <- the only correct ones
--
-- Why it matters now: incident routing picks the supervisor from the reporter's
-- own department. With the reporter filed under another tenant's department,
-- the lookup either finds nobody (and the incident goes unassigned) or, worse,
-- finds a supervisor belonging to a different organisation.
--
-- The seed built each organisation the same eight departments with the same
-- names, so the correct department is the one with a matching name inside the
-- employee's own organisation. Employees already sitting in a department of
-- their own organisation are untouched, which makes this safe to re-run.
--
-- Anything that cannot be matched by name is left alone rather than guessed at,
-- and the final SELECT reports it.
-- ─────────────────────────────────────────────────────────────────────────────

UPDATE employees e
  JOIN departments wrong    ON wrong.id = e.department_id
  JOIN departments correct  ON correct.department_name = wrong.department_name
                           AND correct.organisation_id = e.organisation_id
   SET e.department_id = correct.id
 WHERE e.department_id IS NOT NULL
   AND e.organisation_id IS NOT NULL
   AND wrong.organisation_id <> e.organisation_id;

-- Anything still crossing a tenant boundary after the remap. Expect zero rows.
SELECT e.organisation_id AS employee_org,
       d.organisation_id AS department_org,
       COUNT(*)          AS still_wrong
  FROM employees e
  JOIN departments d ON d.id = e.department_id
 WHERE e.organisation_id IS NOT NULL
   AND d.organisation_id <> e.organisation_id
 GROUP BY e.organisation_id, d.organisation_id;
