-- ─────────────────────────────────────────────────────────────────────────────
-- 069 · Somewhere to put "Other" on a near miss
--
-- The near miss form asks where it happened and which hazard it belongs to,
-- and both answers are integer foreign keys — location_station_id and
-- hazard_id. A worker whose answer is not on either list has nowhere to put it,
-- so the form offered no way out and they had to pick the nearest wrong option.
--
-- These two columns hold the worker's own words for exactly that case. The
-- matching id is left null and the text kept here, rather than the answer being
-- forced onto a station or hazard it does not belong to.
--
-- potential_consequence and underlying_cause already exist on this table and
-- are plain varchars, so they take a listed option or an "Other" answer without
-- any change — one column holding both is what keeps a second "…_is_other"
-- flag from having to be maintained alongside it.
--
-- The same pair was added to risk_reports in 068. That work was reverted in
-- dbdc75d and its columns left in place; this is the sibling table, and the two
-- are named identically so a supervisor reading both meets one vocabulary.
--
-- Both nullable and additive. Every existing row stays valid.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE near_misses
  ADD COLUMN location_other VARCHAR(255) NULL AFTER location_station_id,
  ADD COLUMN hazard_other   VARCHAR(255) NULL AFTER hazard_id;
