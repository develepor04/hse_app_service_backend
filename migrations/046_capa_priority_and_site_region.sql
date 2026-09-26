-- ══════════════════════════════════════════════════════════════════════════════
-- 046 — WF-04 CAPA priority matrix and due-date rules, plus the sub-national
-- region that three Appendix A jurisdictions route on.
--
-- Source: EHSERA AI Orchestration Platform ISMS v1.0:
--   WF-04 "CAPA Priority Matrix" and "CAPA Type Due Date Rules"
--   Appendix A (UAE emirate, Australian state, EU member state)
--
-- capa_actions previously had due_date but nothing that computed it, and no
-- priority at all. WF-04 gives it both: a 1-9 matrix score for review attention,
-- and a P1-P5 type that sets the deadline. The two are independent -- a P1
-- regulatory breach is due in 24 hours whatever its matrix score.
--
-- sites.jurisdiction (migration 045) picks the country. sites.region picks the
-- authority within it: OSHAD-SF vs DCD in the UAE, SafeWork NSW vs WorkSafe VIC
-- in Australia, DGUV vs HSA in the EU.
--
-- NOTE the runner strips comments before splitting, but keep the file ending on
-- a real statement out of habit.
-- ══════════════════════════════════════════════════════════════════════════════

ALTER TABLE sites
  ADD COLUMN region VARCHAR(60) NULL DEFAULT NULL COMMENT 'Emirate (UAE), state (AU), member state (EU)';

ALTER TABLE capa_actions
  ADD COLUMN severity_potential   INT          NULL DEFAULT NULL,
  ADD COLUMN systemic_risk        INT          NULL DEFAULT NULL,
  ADD COLUMN priority_score       INT          NULL DEFAULT NULL,
  ADD COLUMN priority_band        VARCHAR(20)  NULL DEFAULT NULL,
  ADD COLUMN capa_type            VARCHAR(4)   NULL DEFAULT NULL,
  ADD COLUMN capa_type_label      VARCHAR(20)  NULL DEFAULT NULL,
  ADD COLUMN target_hours         INT          NULL DEFAULT NULL,
  ADD COLUMN evidence_required    VARCHAR(255) NULL DEFAULT NULL,
  ADD COLUMN priority_explanation TEXT         NULL;

CREATE INDEX idx_capa_priority ON capa_actions (priority_band, status);
CREATE INDEX idx_capa_type_due ON capa_actions (capa_type, due_date);

-- ── Backfill · existing open CAPAs ───────────────────────────────────────────
-- Existing rows have no severity/systemic inputs recorded, so no matrix score
-- can be reconstructed and none is invented. What CAN be derived is the CAPA
-- type, from the severity of the incident that generated it -- the spec's
-- trigger column maps P1..P5 one-to-one. Rows with no incident, or an incident
-- that predates the P1-P5 classification in migration 045, are left NULL.
UPDATE capa_actions c
  JOIN incidents i ON i.id = c.incident_id
   SET c.capa_type = i.severity_priority,
       c.capa_type_label = CASE i.severity_priority
         WHEN 'P1' THEN 'Immediate' WHEN 'P2' THEN 'Urgent' WHEN 'P3' THEN 'High'
         WHEN 'P4' THEN 'Medium'    WHEN 'P5' THEN 'Low'    ELSE NULL END,
       c.target_hours = CASE i.severity_priority
         WHEN 'P1' THEN 24  WHEN 'P2' THEN 168 WHEN 'P3' THEN 720
         WHEN 'P4' THEN 1440 WHEN 'P5' THEN 2160 ELSE NULL END,
       c.priority_explanation = CONCAT(
         'Backfilled: CAPA type inherited from incident ', i.id,
         ' severity ', COALESCE(i.severity_priority, 'unclassified'),
         '. Matrix score not reconstructable -- severity potential and systemic risk',
         ' were not captured before migration 046.')
 WHERE i.severity_priority IS NOT NULL;
