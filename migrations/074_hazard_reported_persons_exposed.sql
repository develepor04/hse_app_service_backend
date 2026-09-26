-- ─────────────────────────────────────────────────────────────────────────────
-- 074 · The fourth answer 073 missed
--
-- persons_exposed belongs with reported_severity, reported_probability and
-- existing_controls in 073 and was left out. It has the same problem: the
-- worker types how many people are exposed on the log form, then /assess and
-- /findings both write over it with the supervisor's revised count, in place.
--
-- On HAZ-82 the worker reported 6 and the supervisor revised it to 9, and the
-- card headed "reported by the worker" showed 9 — a number that worker never
-- typed, under their name. Same fix, same reasoning as 073.
--
-- Backfilled on 'open' rows only, for the reason 073 gives: past that point the
-- reporter's figure is already gone, and null reads as "not recorded" where a
-- copy would read as the reporter's answer.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE hazards
  ADD COLUMN reported_persons_exposed INT NULL AFTER existing_controls;

UPDATE hazards
   SET reported_persons_exposed = persons_exposed
 WHERE register_status = 'open';
