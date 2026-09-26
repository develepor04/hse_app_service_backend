-- ─────────────────────────────────────────────────────────────────────────────
-- 068 · The context fields a risk report was collecting nowhere
--
-- The risk form asks what the worker saw and how bad it could be, and then had
-- nowhere to put four things a supervisor needs before they can act on it:
--
--   potential_consequence  what kind of harm this could cause. Distinct from
--                          `consequence`, which is the 5x5 severity axis feeding
--                          risk_score = likelihood x consequence. "Lost Time
--                          Injury" is a kind of harm; "major" is a number in
--                          disguise. Conflating them would either break the
--                          scoring or lose the description.
--
--   underlying_cause       the condition behind it — a missing guard, poor
--                          lighting. Not root_cause, which the supervisor
--                          establishes at stage 04 INVESTIGATE and which is
--                          their conclusion rather than the reporter's
--                          observation.
--
--   location_other         where it was, when the place is not one of the
--   hazard_other           registered working stations; and which hazard, when
--                          it is not one on the register. Both are integer
--                          foreign keys, so "Other" has nowhere to go on the
--                          existing columns: the id is left null and the
--                          worker's own words are kept here rather than
--                          discarded.
--
-- The first two mirror `near_misses`, which has carried potential_consequence
-- and underlying_cause since it was built. Risk reports are the sibling table
-- and the same supervisor reads both, so they are named identically.
--
-- All nullable and all additive. Every existing row stays valid, and nothing
-- reads these until the form starts sending them.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE risk_reports
  ADD COLUMN potential_consequence VARCHAR(255) NULL AFTER consequence,
  ADD COLUMN underlying_cause      VARCHAR(255) NULL AFTER potential_consequence,
  ADD COLUMN location_other        VARCHAR(255) NULL AFTER location_station_id,
  ADD COLUMN hazard_other          VARCHAR(255) NULL AFTER hazard_id;
