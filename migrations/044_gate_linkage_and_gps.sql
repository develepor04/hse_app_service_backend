-- ══════════════════════════════════════════════════════════════════════════════
-- 044 — Wire the gate engine into the permit workflow, and finish "GPS on all
-- records" from the Layer 1 mobile shell spec.
--
-- The permit is where five of the six deterministic gates land, so it needs to
-- carry the gate verdict, the contractor it was issued to, and the RAMS score
-- that gate 1 checks for.
-- ══════════════════════════════════════════════════════════════════════════════

-- ── Permit → gate engine linkage (WF-02 gate, fed by WF-06/08/09) ────────────
ALTER TABLE permits_to_work
  ADD COLUMN gate_status            VARCHAR(20)  NULL DEFAULT NULL,
  ADD COLUMN gate_checked_at        DATETIME     NULL,
  ADD COLUMN gate_blocked_reason    TEXT         NULL,
  ADD COLUMN contractor_company_id  INT          NULL,
  ADD COLUMN rams_score_id          INT          NULL,
  ADD COLUMN zone                   VARCHAR(120) NULL,
  ADD COLUMN is_high_energy         TINYINT(1)   NOT NULL DEFAULT 0,
  ADD COLUMN gps_latitude           DECIMAL(10,7) NULL,
  ADD COLUMN gps_longitude          DECIMAL(10,7) NULL;

CREATE INDEX idx_ptw_gate_status ON permits_to_work (gate_status);
CREATE INDEX idx_ptw_contractor  ON permits_to_work (contractor_company_id);
CREATE INDEX idx_ptw_zone        ON permits_to_work (zone);

-- ── GPS on the remaining operational records ─────────────────────────────────
ALTER TABLE audits
  ADD COLUMN gps_latitude  DECIMAL(10,7) NULL,
  ADD COLUMN gps_longitude DECIMAL(10,7) NULL;

ALTER TABLE safety_walks
  ADD COLUMN gps_latitude  DECIMAL(10,7) NULL,
  ADD COLUMN gps_longitude DECIMAL(10,7) NULL;

-- ── Auditor verification on the three factory-built workflows ────────────────
-- Step 4 of the workflow chain requires independent verification recorded
-- against the original record. incidents, permits_to_work and hazards already
-- carry these columns. near_misses, unsafe_acts and risk_reports did not.
ALTER TABLE near_misses
  ADD COLUMN auditor_verified_by  INT         NULL,
  ADD COLUMN auditor_verified_at  DATETIME    NULL,
  ADD COLUMN verification_result  VARCHAR(50) NULL,
  ADD COLUMN verification_notes   TEXT        NULL;

ALTER TABLE unsafe_acts
  ADD COLUMN auditor_verified_by  INT         NULL,
  ADD COLUMN auditor_verified_at  DATETIME    NULL,
  ADD COLUMN verification_result  VARCHAR(50) NULL,
  ADD COLUMN verification_notes   TEXT        NULL;

ALTER TABLE risk_reports
  ADD COLUMN auditor_verified_by  INT         NULL,
  ADD COLUMN auditor_verified_at  DATETIME    NULL,
  ADD COLUMN verification_result  VARCHAR(50) NULL,
  ADD COLUMN verification_notes   TEXT        NULL;

-- incidents got verified_by/at in 041 but no verification_result verdict field
ALTER TABLE incidents
  ADD COLUMN verification_result VARCHAR(50) NULL;
