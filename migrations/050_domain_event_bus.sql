-- ══════════════════════════════════════════════════════════════════════════════
-- 050 — The domain event bus.
--
-- Source: HSE_Workflow_Engine_Slide.pptx — "Every Closure Improves the System.
-- Closing an event updates risk, training, inspections and the AI model
-- automatically." Plus the Architecture doc section 6 (Event Driven Platform).
--
-- Until now closing an incident set workflow_status='closed' and stopped. The
-- linked hazard was not re-reviewed, no competence gap was raised, no follow-up
-- inspection was scheduled. Closure was a dead end, so the third promise on the
-- slide was the one with nothing behind it at all.
--
-- Two tables, deliberately:
--
--   domain_events     the outbox — every event ever published, with its payload.
--                     Written in the SAME transaction as the business change, so
--                     an event cannot exist for a change that rolled back, and a
--                     committed change cannot silently lose its event.
--
--   event_deliveries  one row per (event, handler). Handlers fail independently:
--                     a broken training handler must not stop the inspection
--                     handler, and must not roll back the closure that triggered
--                     it. Each row carries its own status, attempt count and
--                     error, which is what makes replay and a DLQ possible.
--
-- The spec puts this on Azure Service Bus. This is an in-process bus with a
-- durable outbox — same contract, no broker. Swapping the dispatcher for a real
-- queue later does not change the publisher or the handlers.
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS domain_events (
  id               INT AUTO_INCREMENT PRIMARY KEY,
  event_id         VARCHAR(36)  NOT NULL,
  event_type       VARCHAR(60)  NOT NULL,
  schema_version   VARCHAR(10)  NOT NULL DEFAULT '1.0',
  organisation_id  INT          NULL,
  correlation_id   VARCHAR(64)  NULL,
  source_service   VARCHAR(60)  NULL,
  user_id          INT          NULL,

  -- What the event is about, so a consumer can find the record without parsing
  -- the payload.
  subject_family   VARCHAR(30)  NULL,
  subject_id       INT          NULL,

  payload          JSON         NULL,
  published_at     DATETIME     NOT NULL,
  created_at       TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
  updated_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  UNIQUE KEY uq_domain_event_id (event_id),
  INDEX idx_de_type    (event_type, published_at),
  INDEX idx_de_org     (organisation_id, published_at),
  INDEX idx_de_subject (subject_family, subject_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS event_deliveries (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  event_id       VARCHAR(36)  NOT NULL,
  event_type     VARCHAR(60)  NOT NULL,
  handler        VARCHAR(80)  NOT NULL,

  -- pending | delivered | failed | dead
  -- `dead` is the DLQ: retries exhausted, a human needs to look.
  status         VARCHAR(20)  NOT NULL DEFAULT 'pending',
  attempts       INT          NOT NULL DEFAULT 0,
  last_error     TEXT         NULL,
  -- What the handler actually did, so the cascade is auditable rather than
  -- something you infer from side effects across four tables.
  outcome        VARCHAR(255) NULL,
  delivered_at   DATETIME     NULL,
  created_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
  updated_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  -- Idempotency: a handler runs at most once per event, so a replay or a
  -- duplicate publish cannot raise the same competence gap twice.
  UNIQUE KEY uq_event_handler (event_id, handler),
  INDEX idx_ed_status (status, event_type),
  INDEX idx_ed_event  (event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
