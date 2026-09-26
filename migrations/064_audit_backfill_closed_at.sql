-- Migration: 064_audit_backfill_closed_at
-- Give the audits that were closed under the old flow a closure date.
--
-- `closed_at` arrived with 062. Everything closed before it has status
-- 'completed' and a NULL closure date, which forced the step derivation to read
-- "closed" as "closed_at IS NOT NULL OR status = 'completed'".
--
-- That disjunction made reopening impossible. When a 30/60/90-day effectiveness
-- check fails, the audit has to come back out of CLOSE — it is the one thing
-- step 10 exists to catch. Clearing closed_at did nothing, because the status
-- half of the test still answered "closed" and the recomputed status wrote
-- 'completed' straight back over the reopen.
--
-- With a date on every closed row, closed_at is the only thing anything reads.

UPDATE audits
   SET closed_at = COALESCE(submitted_at, updated_at, created_at)
 WHERE closed_at IS NULL
   AND LOWER(status) IN ('completed', 'closed');
