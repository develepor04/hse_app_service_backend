-- ─────────────────────────────────────────────────────────────────────────────
-- 067 · Split the two meanings of permits_to_work.workflow_status = 'expired'
--
-- `expired` was carrying two unrelated states at once.
--
--   1. Work is finished and the permit is spent. Written by
--      /permit-workflow/{id}/complete-work, and the only thing that has ever
--      written this column to 'expired'. Every one of the 1,129 rows holding it
--      today means this.
--
--   2. The validity window closed. The natural reading of the word, mapped in
--      PERMIT_STATUS_STAGE, described in permit_next_action, and shown on the
--      mobile permit screen — but never actually written by anything, because
--      expire_overdue_permits() sets `status` (the website's business field) and
--      not workflow_status, and is not scheduled in any case.
--
-- So the word meant the second thing everywhere it was read and the first thing
-- everywhere it was written. Nothing broke only because meaning 2 never got
-- written. It would have the moment permit expiry was switched on, and the two
-- are not remotely the same: one is a permit that did its job, the other is a
-- permit that lapsed with work possibly still going on under it.
--
-- Meaning 1 becomes 'work_complete'. 'expired' keeps the word's plain meaning
-- and is left free for the expiry sweep, which now has an unambiguous slot to
-- write into whenever the seed data's 2024-2025 validity dates are refreshed.
--
-- Every existing row is meaning 1, so this migration moves all of them. There is
-- nothing to leave behind.
-- ─────────────────────────────────────────────────────────────────────────────

UPDATE permits_to_work
   SET workflow_status = 'work_complete'
 WHERE workflow_status = 'expired';
