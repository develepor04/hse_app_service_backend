-- ─────────────────────────────────────────────────────────────────────────────
-- 084 · Give every report a reporter from its own organisation
--
-- The seed attached reporters from a global employee pool, so a large share of
-- records name somebody who belongs to a different tenant:
--
--     incidents      169 of 270 crossed a tenant boundary
--     near_misses    377 of 540
--     risk_reports     7 of  12
--     hazards         12 of  83
--     permits          10 of 17311
--
-- This was invisible while every queue was org-wide. Now that supervisors and
-- managers see only their own department -- resolved through the reporter --
-- a record whose reporter lives in another organisation belongs to a
-- department that nobody in the owning organisation is in, so it appears in
-- no queue at all.
--
-- Fix: repoint the reporter at an active employee who is in the record's own
-- organisation AND has a department, chosen deterministically by
-- `record.id MOD pool_size` so the records spread across that organisation's
-- departments instead of piling onto one person.
--
-- ONLY rows that are already wrong are touched -- the WHERE requires the
-- current reporter to be in a different organisation. Rows with a NULL
-- reporter are deliberately left alone: inventing a reporter for them would be
-- fabricating data, and the department scope already shows those to everyone
-- rather than hiding them.
--
-- This is seed data being made self-consistent. The application itself cannot
-- produce this state: incident_workflow.py sets organisation_id and reported_by
-- from the same `current_user` on the same request, so they always agree.
-- ─────────────────────────────────────────────────────────────────────────────


UPDATE incidents r
  JOIN employees cur ON cur.id = r.reported_by
  JOIN (
        SELECT e.id, e.organisation_id,
               ROW_NUMBER() OVER (PARTITION BY e.organisation_id ORDER BY e.id) - 1 AS seq,
               COUNT(*)     OVER (PARTITION BY e.organisation_id)                  AS total
          FROM employees e
         WHERE e.department_id IS NOT NULL
           AND e.active_status = 'Active'
           AND e.organisation_id IS NOT NULL
       ) pool ON pool.organisation_id = r.organisation_id
   SET r.reported_by = pool.id
 WHERE cur.organisation_id <> r.organisation_id
   AND pool.seq = r.id MOD pool.total;


UPDATE near_misses r
  JOIN employees cur ON cur.id = r.reported_by
  JOIN (
        SELECT e.id, e.organisation_id,
               ROW_NUMBER() OVER (PARTITION BY e.organisation_id ORDER BY e.id) - 1 AS seq,
               COUNT(*)     OVER (PARTITION BY e.organisation_id)                  AS total
          FROM employees e
         WHERE e.department_id IS NOT NULL
           AND e.active_status = 'Active'
           AND e.organisation_id IS NOT NULL
       ) pool ON pool.organisation_id = r.organisation_id
   SET r.reported_by = pool.id
 WHERE cur.organisation_id <> r.organisation_id
   AND pool.seq = r.id MOD pool.total;


UPDATE risk_reports r
  JOIN employees cur ON cur.id = r.reported_by
  JOIN (
        SELECT e.id, e.organisation_id,
               ROW_NUMBER() OVER (PARTITION BY e.organisation_id ORDER BY e.id) - 1 AS seq,
               COUNT(*)     OVER (PARTITION BY e.organisation_id)                  AS total
          FROM employees e
         WHERE e.department_id IS NOT NULL
           AND e.active_status = 'Active'
           AND e.organisation_id IS NOT NULL
       ) pool ON pool.organisation_id = r.organisation_id
   SET r.reported_by = pool.id
 WHERE cur.organisation_id <> r.organisation_id
   AND pool.seq = r.id MOD pool.total;


UPDATE hazards r
  JOIN employees cur ON cur.id = r.logged_by
  JOIN (
        SELECT e.id, e.organisation_id,
               ROW_NUMBER() OVER (PARTITION BY e.organisation_id ORDER BY e.id) - 1 AS seq,
               COUNT(*)     OVER (PARTITION BY e.organisation_id)                  AS total
          FROM employees e
         WHERE e.department_id IS NOT NULL
           AND e.active_status = 'Active'
           AND e.organisation_id IS NOT NULL
       ) pool ON pool.organisation_id = r.organisation_id
   SET r.logged_by = pool.id
 WHERE cur.organisation_id <> r.organisation_id
   AND pool.seq = r.id MOD pool.total;


UPDATE permits_to_work r
  JOIN employees cur ON cur.id = r.requested_by
  JOIN (
        SELECT e.id, e.organisation_id,
               ROW_NUMBER() OVER (PARTITION BY e.organisation_id ORDER BY e.id) - 1 AS seq,
               COUNT(*)     OVER (PARTITION BY e.organisation_id)                  AS total
          FROM employees e
         WHERE e.department_id IS NOT NULL
           AND e.active_status = 'Active'
           AND e.organisation_id IS NOT NULL
       ) pool ON pool.organisation_id = r.organisation_id
   SET r.requested_by = pool.id
 WHERE cur.organisation_id <> r.organisation_id
   AND pool.seq = r.id MOD pool.total;


-- Anything still crossing a tenant boundary. Expect zero rows.
SELECT 'incidents' AS source, COUNT(*) AS still_wrong
  FROM incidents r JOIN employees e ON e.id = r.reported_by
 WHERE e.organisation_id <> r.organisation_id
UNION ALL
SELECT 'near_misses', COUNT(*)
  FROM near_misses r JOIN employees e ON e.id = r.reported_by
 WHERE e.organisation_id <> r.organisation_id
UNION ALL
SELECT 'risk_reports', COUNT(*)
  FROM risk_reports r JOIN employees e ON e.id = r.reported_by
 WHERE e.organisation_id <> r.organisation_id
UNION ALL
SELECT 'hazards', COUNT(*)
  FROM hazards r JOIN employees e ON e.id = r.logged_by
 WHERE e.organisation_id <> r.organisation_id
UNION ALL
SELECT 'permits_to_work', COUNT(*)
  FROM permits_to_work r JOIN employees e ON e.id = r.requested_by
 WHERE e.organisation_id <> r.organisation_id;
