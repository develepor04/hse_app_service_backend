-- ─────────────────────────────────────────────────────────────────────────────
-- Fix production logins that are not linked to an organisation or an employee.
--
-- SYMPTOMS THIS EXPLAINS
--   · every dashboard tile blank ("—") while the user's own name loads fine
--   · "Failed to submit — No such employee" when a corrective action is filled in
--   · lists empty even though the data plainly exists
--
-- WHY
--   app/core/dependencies.py resolves the caller's organisation as
--       org_id = users.organisation_id   (falling back to the JWT claim)
--   and when that is NULL it substitutes the sentinel -1:
--       "Normal tenant users without completed organisation setup must not see
--        global/seed rows ... use an impossible id to produce empty results."
--   Every tenant query then runs WHERE organisation_id = -1 and matches nothing.
--   The CAPA owner check has the same shape, which is why it reports
--   "No such employee" for somebody plainly on the list:
--       SELECT id FROM employees WHERE id = :picked AND organisation_id = -1
--
--   Separately, users.employee_id is what _employee_id() resolves for "my"
--   scoping (my incidents, my tasks, my hours). NULL there means every personal
--   query matches nothing even once the organisation is correct.
--
-- NOTE ON MATCHING
--   `employees` has no email column -- the only field shared with `users` is
--   full_name. Name matching is not trustworthy on its own, so section 3 links
--   ONLY where exactly one employee carries that name. Ambiguous and unmatched
--   rows are listed by section 4 and must be linked by hand in section 5.
--
--   superadmin is exempt on purpose -- dependencies.py only substitutes the
--   sentinel when role != 'superadmin' -- so every query below skips app_role_id 1
--   (app_roles.name = 'superadmin'). Without that it is a permanent false positive.
--
-- RUN THE SELECTS FIRST. Back up `users` before any UPDATE:
--   mysqldump <db> users > users_backup_$(date +%F).sql
-- ─────────────────────────────────────────────────────────────────────────────


-- ── 1. WHO IS BROKEN ─────────────────────────────────────────────────────────
SELECT u.id              AS user_id,
       u.username,
       u.full_name,
       u.organisation_id AS user_org,      -- NULL -> org_id becomes -1
       u.employee_id     AS user_emp,      -- NULL -> "my" queries match nothing
       e.full_name       AS linked_employee,
       e.organisation_id AS employee_org   -- must agree with user_org
  FROM users u
  LEFT JOIN employees e ON e.id = u.employee_id
 WHERE (u.organisation_id IS NULL OR u.employee_id IS NULL)
   AND u.app_role_id <> 1          -- superadmin is legitimately org-less
 ORDER BY u.id;


-- ── 2. PROPOSED LINKS, WITH THE AMBIGUITY EXPOSED ────────────────────────────
-- `candidates` is how many employees share that name. Only 1 is safe to
-- auto-link. Review this before running section 3.
SELECT u.id AS user_id, u.username, u.full_name,
       (SELECT COUNT(*) FROM employees e
         WHERE e.full_name = u.full_name)               AS candidates,
       (SELECT MIN(e.id) FROM employees e
         WHERE e.full_name = u.full_name)               AS employee_id,
       (SELECT MIN(e.organisation_id) FROM employees e
         WHERE e.full_name = u.full_name)               AS org_id
  FROM users u
 WHERE (u.employee_id IS NULL OR u.organisation_id IS NULL)
   AND u.app_role_id <> 1
 ORDER BY candidates DESC, u.id;


-- ── 3. FIX A: link user -> employee, ONLY where the name is unambiguous ──────
-- The HAVING COUNT(*) = 1 guard is the whole point: a wrong link is worse than
-- no link, because reads then silently return another person's records.
UPDATE users u
  JOIN (
        SELECT e.full_name, MIN(e.id) AS emp_id, MIN(e.organisation_id) AS org_id
          FROM employees e
         WHERE e.full_name IS NOT NULL AND e.full_name <> ''
         GROUP BY e.full_name
        HAVING COUNT(*) = 1
       ) m ON m.full_name = u.full_name
   SET u.employee_id     = COALESCE(u.employee_id, m.emp_id),
       u.organisation_id = COALESCE(u.organisation_id, m.org_id)
 WHERE (u.employee_id IS NULL OR u.organisation_id IS NULL)
   AND u.app_role_id <> 1;


-- ── 4. WHAT SECTION 3 COULD NOT SETTLE ───────────────────────────────────────
-- Duplicate names, or no employee record at all. These need section 5.
SELECT u.id AS user_id, u.username, u.full_name,
       u.organisation_id, u.employee_id,
       (SELECT COUNT(*) FROM employees e WHERE e.full_name = u.full_name) AS candidates
  FROM users u
 WHERE (u.organisation_id IS NULL OR u.employee_id IS NULL)
   AND u.app_role_id <> 1
 ORDER BY u.id;


-- ── 5. FIX B: one specific login, by hand ────────────────────────────────────
-- For each row section 4 returned, find the right employee:
--     SELECT id, full_name, organisation_id, role_id, active_status
--       FROM employees
--      WHERE full_name LIKE '%<part of the name>%';
-- then set both columns together so they cannot disagree:
--
--   UPDATE users
--      SET employee_id     = <employees.id>,
--          organisation_id = <that employee's organisation_id>
--    WHERE id = <users.id>;


-- ── 6. VERIFY ────────────────────────────────────────────────────────────────
-- Expect zero rows.
SELECT u.id, u.username, u.full_name, u.organisation_id, u.employee_id
  FROM users u
 WHERE (u.organisation_id IS NULL OR u.employee_id IS NULL)
   AND u.app_role_id <> 1
 ORDER BY u.id;


-- ── 7. CONSISTENCY CHECK ─────────────────────────────────────────────────────
-- A user whose organisation disagrees with their employee's is worse than a
-- NULL: reads scope to one organisation while writes stamp the other.
-- Expect zero rows.
SELECT u.id AS user_id, u.username,
       u.organisation_id AS user_org,
       e.organisation_id AS employee_org
  FROM users u
  JOIN employees e ON e.id = u.employee_id
 WHERE u.organisation_id <> e.organisation_id;
