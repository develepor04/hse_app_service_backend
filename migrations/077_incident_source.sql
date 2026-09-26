-- ─────────────────────────────────────────────────────────────────────────────
-- 077 · A real column for where an incident came from
--
-- The client asked the web incident register to distinguish mobile-submitted,
-- web-registered and imported incidents. Nothing recorded that — Incident.source
-- (models/incident.py) was a computed property guessing "Mobile App" if either
-- GPS field was set, "Web App" otherwise. That guess was never actually true for
-- any row: no web registration path existed yet, so every GPS-less incident —
-- mobile submissions with location permission denied, seeded data, imported
-- history — was mislabelled "Web App" by exclusion, not because it came from one.
--
-- Backfilled only into "Mobile App" (GPS present) or "Legacy" (GPS absent, no
-- way to know) — not "Web App", because it was factually impossible for any
-- existing row to have come from a feature that did not exist yet. Every write
-- path from here on stamps this column explicitly instead of leaving it to be
-- inferred: worker.py's /worker/incidents endpoint, the new web registration
-- form (both explicit), and the Excel bulk importer ("Data Import").
--
-- Nullable and additive. Every existing row stays valid.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE incidents
  ADD COLUMN source VARCHAR(20) NULL AFTER investigation_status;

UPDATE incidents
   SET source = CASE
                   WHEN gps_latitude IS NOT NULL OR gps_longitude IS NOT NULL THEN 'Mobile App'
                   ELSE 'Legacy'
                 END
 WHERE source IS NULL;
