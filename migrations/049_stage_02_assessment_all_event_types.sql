-- ══════════════════════════════════════════════════════════════════════════════
-- 049 — Stage 02 ASSESS for near misses, unsafe acts and risk reports.
--
-- Source: HSE_Workflow_Engine_Slide.pptx — "One Workflow Engine. Every Safety
-- Event. Hazards, near misses, incidents, permits and audits all flow through
-- the same 8 stages."
--
-- Only incidents were assessed. Everything else went from RECORD straight to a
-- supervisor queue with no triage, so nothing decided how urgently a near miss
-- or a raised risk should be handled, and a near miss that could have killed
-- someone looked identical to a trivial one.
--
-- These columns mirror the ones migration 045 added to `incidents`, so the four
-- report families can be ranked against each other in one queue. They are
-- deliberately named generically (assessed_priority, not severity_priority)
-- because a risk report has no "severity" in the incident sense — it has a band
-- that maps onto the same P1-P5 urgency scale.
--
-- No `stage` column: the stage is derived from workflow_status by
-- app.services.workflow_stages. A stored copy would drift.
-- ══════════════════════════════════════════════════════════════════════════════

ALTER TABLE near_misses
  ADD COLUMN assessed_priority     VARCHAR(4)   NULL DEFAULT NULL,
  ADD COLUMN assessed_label        VARCHAR(60)  NULL DEFAULT NULL,
  ADD COLUMN is_hipo               TINYINT(1)   NOT NULL DEFAULT 0,
  ADD COLUMN is_recurring_pattern  TINYINT(1)   NOT NULL DEFAULT 0,
  ADD COLUMN requires_systemic_rca TINYINT(1)   NOT NULL DEFAULT 0,
  ADD COLUMN response_due_at       DATETIME     NULL,
  ADD COLUMN min_investigator      VARCHAR(60)  NULL DEFAULT NULL,
  ADD COLUMN assessment_trace      TEXT         NULL,
  ADD COLUMN assessed_at           DATETIME     NULL;

ALTER TABLE unsafe_acts
  ADD COLUMN assessed_priority     VARCHAR(4)   NULL DEFAULT NULL,
  ADD COLUMN assessed_label        VARCHAR(60)  NULL DEFAULT NULL,
  ADD COLUMN is_hipo               TINYINT(1)   NOT NULL DEFAULT 0,
  ADD COLUMN is_recurring_pattern  TINYINT(1)   NOT NULL DEFAULT 0,
  ADD COLUMN requires_systemic_rca TINYINT(1)   NOT NULL DEFAULT 0,
  ADD COLUMN response_due_at       DATETIME     NULL,
  ADD COLUMN min_investigator      VARCHAR(60)  NULL DEFAULT NULL,
  ADD COLUMN assessment_trace      TEXT         NULL,
  ADD COLUMN assessed_at           DATETIME     NULL;

ALTER TABLE risk_reports
  ADD COLUMN assessed_priority     VARCHAR(4)   NULL DEFAULT NULL,
  ADD COLUMN assessed_label        VARCHAR(60)  NULL DEFAULT NULL,
  ADD COLUMN is_hipo               TINYINT(1)   NOT NULL DEFAULT 0,
  ADD COLUMN is_recurring_pattern  TINYINT(1)   NOT NULL DEFAULT 0,
  ADD COLUMN requires_systemic_rca TINYINT(1)   NOT NULL DEFAULT 0,
  ADD COLUMN response_due_at       DATETIME     NULL,
  ADD COLUMN min_investigator      VARCHAR(60)  NULL DEFAULT NULL,
  ADD COLUMN assessment_trace      TEXT         NULL,
  ADD COLUMN assessed_at           DATETIME     NULL;

CREATE INDEX idx_nm_assessed  ON near_misses (assessed_priority, response_due_at);
CREATE INDEX idx_ua_assessed  ON unsafe_acts (assessed_priority, response_due_at);
CREATE INDEX idx_rr_assessed  ON risk_reports (assessed_priority, response_due_at);

-- The recurrence check filters on station + type + date on every submission.
-- near_misses has no event-type column, so the linked hazard is the closest
-- proxy for "the same thing happening again at this station".
CREATE INDEX idx_nm_recurrence ON near_misses (organisation_id, location_station_id, hazard_id, created_at);
CREATE INDEX idx_ua_repeat     ON unsafe_acts (organisation_id, person_observed, created_at);
CREATE INDEX idx_rr_recurrence ON risk_reports (organisation_id, location_station_id, risk_category, created_at);

-- ── Backfill · risk reports only ─────────────────────────────────────────────
-- Risk reports already carry a band from migration 045, so their priority can
-- be derived without inventing anything. Near misses and unsafe acts are left
-- NULL: their assessment needs potential-consequence and repeat-history inputs
-- that historical rows never captured, and guessing a priority would put a
-- fabricated response deadline on a real record.
UPDATE risk_reports
   SET assessed_priority = CASE risk_band
         WHEN 'Critical' THEN 'P2' WHEN 'High' THEN 'P3'
         WHEN 'Medium'   THEN 'P4' WHEN 'Low'  THEN 'P5' ELSE NULL END,
       assessed_label = CASE risk_band
         WHEN 'Critical' THEN 'P2 — Serious / LTI'
         WHEN 'High'     THEN 'P3 — Recordable (MTC)'
         WHEN 'Medium'   THEN 'P4 — First Aid / Observation'
         WHEN 'Low'      THEN 'P5 — Near Miss / Observation' ELSE NULL END,
       min_investigator = CASE risk_band
         WHEN 'Critical' THEN 'Safety Manager' WHEN 'High' THEN 'Safety Advisor'
         WHEN 'Medium'   THEN 'Safety Team'    WHEN 'Low'  THEN 'Supervisor' ELSE NULL END,
       assessment_trace = CONCAT('Backfilled from risk band ', COALESCE(risk_band, 'unbanded'),
                                 ' at migration 049. Recurrence not evaluated for historical rows.')
 WHERE risk_band IS NOT NULL;
