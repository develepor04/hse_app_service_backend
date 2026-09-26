-- ─────────────────────────────────────────────────────────────────────────────
-- 071 · WF-01 · the four ways Flow A and Flow B feed each other
--
-- The spec: "They are separate journeys but not separate worlds. Each one keeps
-- the other honest." Four links, and none of them had anywhere to be recorded.
--
--   B -> PERMIT   "No assessment, no permit." The gate has to be able to name
--                 which assessment authorises a permit, so the permit carries
--                 the link rather than the gate guessing from a description.
--
--   A -> B        "A reported hazard can force a reassessment." A hazard raised
--                 in an area an approved assessment covers is evidence that
--                 assessment missed something, so it is flagged for review
--                 rather than quietly left standing.
--
--   B -> A        "An assessment populates the register." Every hazard found in
--                 the ten-category checklist becomes a register entry, so it is
--                 tracked as a live thing instead of living only inside one
--                 document. risk_assessment_hazards.hazard_id already exists for
--                 this, from migration 070.
--
--   INCIDENT -> B "An incident re-opens the assessment", fast-tracked within 48
--                 hours. reopened_reason and reopened_at already exist; what was
--                 missing is the deadline that makes "fast-tracked" mean
--                 something a queue can sort on.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE permits_to_work
  ADD COLUMN risk_assessment_id INT NULL AFTER rams_score_id;

ALTER TABLE risk_assessments
  ADD COLUMN flagged_for_review TINYINT DEFAULT 0 AFTER reopened_at,
  ADD COLUMN flagged_reason     VARCHAR(255) NULL AFTER flagged_for_review,
  ADD COLUMN flagged_at         DATETIME NULL AFTER flagged_reason,
  ADD COLUMN review_due_by      DATETIME NULL AFTER flagged_at;
