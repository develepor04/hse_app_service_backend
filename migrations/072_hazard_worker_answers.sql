-- ─────────────────────────────────────────────────────────────────────────────
-- 072 · The two answers the hazard form threw away
--
-- Log a Hazard asks the worker where the hazard is and whether the danger is
-- still active. Neither answer reached the database.
--
-- `location` was posted as free text and resolved through station_id_for(),
-- which returns an id only on an exact station_name match. The field's own
-- placeholder invites "Bay 4, Loading Dock" — text no station is called — so a
-- worker who typed where the hazard was had location_station_id set to null and
-- their words dropped on the floor. The supervisor then opened a hazard with no
-- location at all. `location_other` keeps the text for that case, the same
-- column near_misses got in 069 and under the same name, so a supervisor
-- reading both meets one vocabulary.
--
-- `still_present` is the form's "It is still there" toggle. It was collected,
-- rendered, defaulted to true, and never sent — a control that looked like it
-- did something. It is the one answer that decides whether the hazard needs an
-- interim control today or can wait for the review, which makes it the worst
-- one to have been dropping.
--
-- Both nullable and additive. Existing rows stay valid; still_present is null
-- for them rather than 0, because "nobody was asked" and "the worker said no"
-- are not the same answer and only one of them should show on a card.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE hazards
  ADD COLUMN location_other VARCHAR(255) NULL AFTER location_station_id,
  ADD COLUMN still_present  TINYINT(1)   NULL AFTER location_other;
