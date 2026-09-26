-- ─────────────────────────────────────────────────────────────────────────────
-- 076 · Photos and video on a hazard
--
-- Every other report family carries evidence_json and has since the forms grew
-- a camera button: incidents, near misses, unsafe acts and risk reports all let
-- the worker photograph what they found, and all four now show it to the
-- supervisor and the manager. The hazard register is the one that cannot.
--
-- It is the family that needs it most. A hazard is a standing condition that
-- somebody has to go and look at, control, and later verify — and "unguarded
-- conveyor pinch point" in a text box tells the person planning that control
-- far less than a photograph of the guard that is missing. The verification
-- stage has the same problem in reverse: there is nothing to compare against.
--
-- Same column name and same shape as the other four, so report_media and the
-- record cards need no special case for hazards.
--
-- Nullable and additive. Every existing row stays valid.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE hazards
  ADD COLUMN evidence_json JSON NULL AFTER gps_longitude;
