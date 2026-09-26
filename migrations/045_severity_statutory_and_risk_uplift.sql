-- ══════════════════════════════════════════════════════════════════════════════
-- 045 — WF-03 P1-P5 severity classification with statutory reporting, and the
-- WF-01 mandatory risk uplifts.
--
-- Source: EHSERA AI Orchestration Platform ISMS v1.0 (client, Aug 2026):
--   WF-03 "Severity Decision Tree" and "Investigation SLA & Severity Matrix"
--   WF-01 steps 4-5 and 8, "Risk Scoring Matrix" and "Risk Band Definitions"
--   Appendix A "Statutory Reporting Reference"
--
-- Two behaviour changes land here.
--
-- 1. incidents.severity was a free-text field and severity_classification used
--    a different taxonomy (LTI / MTI / First Aid / Near Miss). Neither drives
--    anything. The P1-P5 priority does drive the investigation SLA and the
--    regulator deadline, so it gets its own column plus the decision trace that
--    produced it. The old columns are left alone -- the website reads them.
--
-- 2. risk_reports stored only the raw L x S product. The four mandatory uplifts
--    were never applied, so a Medium risk never escalated to High for a new
--    worker on nights without a RAMS. Raw and adjusted are now both stored, so
--    an auditor can see the uplift that changed the verdict.
--
-- NOTE the migration runner splits this file on semicolons, so no semicolon may
-- appear inside a comment.
-- ══════════════════════════════════════════════════════════════════════════════

-- ── Site jurisdiction · drives Appendix A reportability ──────────────────────
-- Nullable on purpose. A site with no jurisdiction returns "cannot determine"
-- rather than defaulting to UK and inventing a legal obligation.
ALTER TABLE sites
  ADD COLUMN jurisdiction VARCHAR(8) NULL DEFAULT NULL COMMENT 'UK|US|UAE|KSA|AU|EU per Appendix A';

-- ── WF-03 · severity classification ──────────────────────────────────────────
ALTER TABLE incidents
  ADD COLUMN severity_priority       VARCHAR(4)   NULL DEFAULT NULL,
  ADD COLUMN severity_label          VARCHAR(60)  NULL DEFAULT NULL,
  ADD COLUMN treatment_level         VARCHAR(40)  NULL DEFAULT NULL,
  ADD COLUMN dangerous_occurrence    TINYINT(1)   NOT NULL DEFAULT 0,
  ADD COLUMN worst_case_fatal        TINYINT(1)   NOT NULL DEFAULT 0,
  ADD COLUMN is_hipo                 TINYINT(1)   NOT NULL DEFAULT 0,
  ADD COLUMN is_recurring_pattern    TINYINT(1)   NOT NULL DEFAULT 0,
  ADD COLUMN requires_systemic_rca   TINYINT(1)   NOT NULL DEFAULT 0,
  ADD COLUMN severity_trace          TEXT         NULL,
  ADD COLUMN severity_classified_at  DATETIME     NULL,
  ADD COLUMN investigation_due_at    DATETIME     NULL,
  ADD COLUMN min_investigator        VARCHAR(60)  NULL DEFAULT NULL;

-- ── Appendix A · statutory notification ──────────────────────────────────────
-- statutory_authorised_* is the human gate. The platform drafts the obligation
-- and never submits it -- Appendix A requires a Safety Manager to authorise.
-- The pre-existing incidents.regulatory_notified stays as the manager-facing
-- Yes/No on the closure form.
ALTER TABLE incidents
  ADD COLUMN statutory_reportable     TINYINT(1)  NOT NULL DEFAULT 0,
  ADD COLUMN statutory_jurisdiction   VARCHAR(8)  NULL DEFAULT NULL,
  ADD COLUMN statutory_regulator      VARCHAR(120) NULL DEFAULT NULL,
  ADD COLUMN statutory_obligations    JSON        NULL,
  ADD COLUMN statutory_due_at         DATETIME    NULL,
  ADD COLUMN statutory_summary        VARCHAR(500) NULL DEFAULT NULL,
  ADD COLUMN statutory_authorised_by  INT         NULL,
  ADD COLUMN statutory_authorised_at  DATETIME    NULL,
  ADD COLUMN statutory_reference      VARCHAR(120) NULL DEFAULT NULL;

CREATE INDEX idx_incidents_severity_priority ON incidents (severity_priority);
CREATE INDEX idx_incidents_statutory_due     ON incidents (statutory_reportable, statutory_due_at);
CREATE INDEX idx_incidents_investigation_due ON incidents (investigation_due_at);

-- Recurrence (WF-03 Q5) asks "same event type at this site in the last 12
-- months". That query filters on type plus station plus date, so it gets a
-- covering index -- it runs on every incident submission.
CREATE INDEX idx_incidents_recurrence ON incidents (organisation_id, incident_type, location_station_id, incident_date_time);

-- ── WF-01 · risk uplifts ─────────────────────────────────────────────────────
-- risk_score is left as the raw L x S so nothing that already reads it breaks.
-- adjusted_risk_score is the number that now drives banding and approval.
ALTER TABLE risk_reports
  ADD COLUMN raw_risk_score            INT         NULL DEFAULT NULL,
  ADD COLUMN uplift_no_valid_rams      TINYINT(1)  NOT NULL DEFAULT 0,
  ADD COLUMN uplift_new_worker         TINYINT(1)  NOT NULL DEFAULT 0,
  ADD COLUMN uplift_night_shift        TINYINT(1)  NOT NULL DEFAULT 0,
  ADD COLUMN uplift_temporary_control  TINYINT(1)  NOT NULL DEFAULT 0,
  ADD COLUMN uplift_total              INT         NOT NULL DEFAULT 0,
  ADD COLUMN adjusted_risk_score       INT         NULL DEFAULT NULL,
  ADD COLUMN risk_band                 VARCHAR(20) NULL DEFAULT NULL,
  ADD COLUMN risk_colour               VARCHAR(20) NULL DEFAULT NULL,
  ADD COLUMN review_frequency          VARCHAR(20) NULL DEFAULT NULL,
  ADD COLUMN approval_route            VARCHAR(40) NULL DEFAULT NULL,
  ADD COLUMN blocks_work               TINYINT(1)  NOT NULL DEFAULT 0,
  ADD COLUMN risk_explanation          TEXT        NULL;

CREATE INDEX idx_risk_reports_band ON risk_reports (risk_band, blocks_work);

-- ── Backfill · existing rows ─────────────────────────────────────────────────
-- Existing risk reports have a raw score and no uplift flags recorded. Copy the
-- raw across and band it, so the new columns are populated consistently. With
-- all four uplift flags at 0 the adjusted score equals the raw score, which is
-- exactly the behaviour those rows were scored under.
--
-- Existing incidents are deliberately NOT backfilled with a P1-P5 priority. The
-- decision tree needs treatment level and worst-case potential, which historical
-- rows never captured -- inventing a priority would put a fabricated regulator
-- deadline on a real record. They stay NULL and read as "unclassified" until
-- someone reopens them.
--
-- This UPDATE is the last statement in the file on purpose. The runner executes
-- every non-empty fragment after splitting on semicolons, and a trailing
-- comment block would be sent to MySQL as an empty query (error 1065), which
-- the runner does not catch.
UPDATE risk_reports
   SET raw_risk_score      = risk_score,
       adjusted_risk_score = risk_score,
       risk_band = CASE
         WHEN risk_score >= 21 THEN 'Critical'
         WHEN risk_score >= 15 THEN 'High'
         WHEN risk_score >= 7  THEN 'Medium'
         WHEN risk_score >= 1  THEN 'Low'
         ELSE NULL END,
       risk_colour = CASE
         WHEN risk_score >= 21 THEN 'Red'
         WHEN risk_score >= 15 THEN 'Orange'
         WHEN risk_score >= 7  THEN 'Amber'
         WHEN risk_score >= 1  THEN 'Green'
         ELSE NULL END,
       review_frequency = CASE
         WHEN risk_score >= 21 THEN 'Monthly'
         WHEN risk_score >= 15 THEN 'Quarterly'
         WHEN risk_score >= 7  THEN '6-monthly'
         WHEN risk_score >= 1  THEN 'Annual'
         ELSE NULL END,
       approval_route = CASE
         WHEN risk_score >= 21 THEN 'Executive'
         WHEN risk_score >= 15 THEN 'Safety Manager'
         WHEN risk_score >= 7  THEN 'Safety Manager'
         WHEN risk_score >= 1  THEN 'Supervisor'
         ELSE NULL END,
       blocks_work = CASE WHEN risk_score >= 15 THEN 1 ELSE 0 END,
       risk_explanation = CONCAT('Backfilled from raw L x S = ', COALESCE(risk_score, 0),
                                 '. Uplift flags were not captured before migration 045.')
 WHERE risk_score IS NOT NULL;
