-- ─────────────────────────────────────────────────────────────────────────────
-- 075 · Somewhere to put the worker's suggestion on a near miss
--
-- ReportNearMissScreen ends with "Preventative Suggestion — how can we prevent
-- this in the future?". The screen collects it, the submit sends it as
-- `preventative_suggestion`, and nothing on the server has ever had that name:
-- NearMissReport does not declare the field, so Pydantic drops it, and
-- near_misses has no column to hold it. The answer to the one question that
-- asks the person closest to the work how to stop it happening again has been
-- going nowhere since the screen was written.
--
-- Named to match risk_reports.suggested_controls, which holds the same thing
-- from the same kind of question, so a supervisor reading a near miss and a
-- risk meets one word for one idea. The request field keeps the form's own
-- name and is mapped across in the controller — renaming the client field
-- would break the offline queue's stored bodies.
--
-- Nullable and additive. Every existing row stays valid.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE near_misses
  ADD COLUMN suggested_controls TEXT NULL AFTER underlying_cause;
