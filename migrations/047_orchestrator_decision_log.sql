-- ══════════════════════════════════════════════════════════════════════════════
-- 047 — The AI Orchestrator decision log.
--
-- Source: EHSERA AI Platform Enterprise Architecture ISMS v1.0:
--   Section 1.2 step 8 "Audit Record Write"
--   Section 8.1 Audit Store -- "REGULATORY, immutable, 10-year retention"
--   Section 10.3 "explanation payloads are write-once"
--
-- One row per orchestrator decision. This is what makes an AI decision
-- replayable during a regulatory audit: which capability version was active,
-- which engines were considered and why each was skipped, what confidence came
-- back, and which pathway that produced.
--
-- Only the SHA-256 of the input is stored, never the input itself (Section 1.2
-- and 11.3). The safety record already lives in its own table -- duplicating it
-- here would spread PII across another store with a longer retention.
--
-- Append-only is enforced in application code, not by MySQL. The spec puts this
-- in Azure Data Explorer where the storage engine guarantees it. On MySQL the
-- honest position is that a DBA can still edit rows -- noted so nobody claims
-- immutability we do not have.
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS orchestrator_decisions (
  id                  INT AUTO_INCREMENT PRIMARY KEY,
  organisation_id     INT          NULL,
  user_id             INT          NULL,
  correlation_id      VARCHAR(64)  NULL,

  capability_id       VARCHAR(40)  NOT NULL,
  capability_version  VARCHAR(20)  NULL,

  engine_selected     VARCHAR(40)  NULL,
  engines_tried       JSON         NULL,
  engines_skipped     JSON         NULL,

  confidence          DECIMAL(6,4) NULL,
  threshold_applied   DECIMAL(6,4) NULL,
  pathway             VARCHAR(20)  NULL,

  requires_hitl       TINYINT(1)   NOT NULL DEFAULT 0,
  hitl_reason         VARCHAR(255) NULL,
  hitl_sla_minutes    INT          NULL,
  hitl_due_at         DATETIME     NULL,

  input_hash          VARCHAR(64)  NULL,
  explanation         TEXT         NULL,

  latency_ms          INT          NULL,
  cost                DECIMAL(10,6) NOT NULL DEFAULT 0,

  created_at          TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,

  INDEX idx_orch_capability (capability_id, created_at),
  INDEX idx_orch_pathway    (pathway, created_at),
  INDEX idx_orch_hitl       (requires_hitl, hitl_due_at),
  INDEX idx_orch_org        (organisation_id, created_at),
  INDEX idx_orch_engine     (engine_selected, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
