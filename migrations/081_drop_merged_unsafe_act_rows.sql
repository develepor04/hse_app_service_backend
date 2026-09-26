-- ─────────────────────────────────────────────────────────────────────────────
-- 081 · Remove the unsafe_acts rows that 080 copied onto the register
--
-- 080 copied rather than moved, on purpose: until the fold-in had been checked
-- against live screens there had to be a way back to the originals. It has now
-- been checked -- all 8 rows matched their copies on description, organisation,
-- reporter and act type, with the workflow vocabulary mapped across -- and the
-- three surfaces that read this table have been removed:
--
--   web      /unsafe-acts/reported and its tracking page
--   manager  the "Unsafe Acts (reported before merge)" card
--   worker   ReportUnsafeActScreen and its dashboard quick action
--
-- Leaving the rows would mean the same unsafe act sitting in two tables with
-- two independent workflow states, and nothing in the UI to reconcile them.
--
-- Only rows with a confirmed copy are removed. Anything in unsafe_acts without
-- a matching hazards.merged_from_unsafe_act_id is left alone -- it would mean a
-- report arrived after 080 ran, and that needs folding in, not deleting.
--
-- The table itself stays. /unsafe-act-workflow and /unsafe-act-trail still
-- mount against it, and the JSON backup taken before this ran is at
-- migrations/backup_unsafe_acts_pre_080_cleanup.json
-- ─────────────────────────────────────────────────────────────────────────────

DELETE ua FROM unsafe_acts ua
JOIN hazards h ON h.merged_from_unsafe_act_id = ua.id;
