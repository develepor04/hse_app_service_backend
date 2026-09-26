-- ══════════════════════════════════════════════════════════════════════════════
-- 048 — Add the updated_at column 047 omitted from orchestrator_decisions.
--
-- app.models.base.Base gives every ORM model id + created_at + updated_at, so
-- SQLAlchemy selects updated_at on every query. Migration 047 declared id and
-- created_at but not updated_at, which made GET /ai/decisions fail with
-- MySQL 1054 "Unknown column 'orchestrator_decisions.updated_at'".
--
-- 047 is left as it was applied rather than edited. A fresh database runs 047
-- then 048 and ends in the same place.
--
-- The column exists to satisfy the base model. It is not meaningful here: the
-- decision log is append-only, so nothing ever updates a row.
-- ══════════════════════════════════════════════════════════════════════════════

ALTER TABLE orchestrator_decisions
  ADD COLUMN updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP;
