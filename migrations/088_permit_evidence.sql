-- ─────────────────────────────────────────────────────────────────────────────
-- 077 · The risk assessment a worker attaches to a permit request
--
-- The permit form has asked for one since it was written — step 4 renders an
-- "Attach Risk Assessment (JSA)" box — and there has never been anywhere to put
-- it. The box had no handler, so tapping it did nothing, and had it worked the
-- request would have had no column to land in.
--
-- That is not a cosmetic gap. `gate_rams_linked` hard-blocks issuance with "No
-- approved risk assessment covers this work. No assessment, no permit." The
-- gate reads `risk_assessment_id`, a link to a Flow-B assessment raised
-- elsewhere — which is right for the formal case and no help at all to a worker
-- standing at the job with the JSA in their hand. The attachment does not
-- satisfy the gate and is not meant to: it is what the supervisor and the
-- manager read while deciding, and what the auditor finds on the record
-- afterwards.
--
-- Same column name and same shape as the five report families already use
-- (incidents, near misses, unsafe acts, risk reports, hazards — see 076), so
-- `report_media` needs no special case for permits and the record cards render
-- it the way they render everything else.
--
-- Nullable and additive. Every existing permit stays valid.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE permits_to_work
  ADD COLUMN evidence_json JSON NULL AFTER gps_longitude;
