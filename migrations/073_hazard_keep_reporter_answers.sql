-- ─────────────────────────────────────────────────────────────────────────────
-- 073 · Stop the supervisor's assessment overwriting the worker's report
--
-- Three columns on `hazards` were being written by the worker and then written
-- over by the supervisor, in place:
--
--   severity, probability  — /assess sets both to the assessor's own scoring,
--                            so after stage 02 the reporter's answer is gone.
--   controls               — /plan-controls copies planned_controls into it, so
--                            "what is already protecting people" becomes "what
--                            we intend to fit".
--
-- Nothing read the originals afterwards, so nothing looked broken. But the
-- register is the record of what was found and by whom, and a card headed
-- "reported by the worker" that shows the assessor's numbers is worse than one
-- that shows nothing: it attributes the assessment to the reporter.
--
-- These three hold the reporter's own answers, written once when the hazard is
-- logged and never touched again. severity/probability/controls keep their
-- current meaning and their existing readers — the website's register list
-- still renders `controls`, and the assessor still scores on `severity` — so
-- nothing downstream changes.
--
-- Backfill covers only rows still at register_status 'open'. On those, nobody
-- has assessed yet, so the three live columns still hold exactly what the
-- reporter typed and copying them across is correct. On rows past that point
-- the original is already lost, and these stay null: a null reads as "not
-- recorded", which is true, where a copied assessment would read as the
-- reporter's answer, which is not.
--
-- All three nullable and additive. Every existing row stays valid.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE hazards
  ADD COLUMN reported_severity    VARCHAR(50)  NULL AFTER probability,
  ADD COLUMN reported_probability VARCHAR(50)  NULL AFTER reported_severity,
  ADD COLUMN existing_controls    TEXT         NULL AFTER reported_probability;

UPDATE hazards
   SET reported_severity    = severity,
       reported_probability = probability,
       existing_controls    = controls
 WHERE register_status = 'open';
