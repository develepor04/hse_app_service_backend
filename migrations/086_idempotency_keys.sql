-- ─────────────────────────────────────────────────────────────────────────────
-- 086 · Idempotency keys (mobile offline-queue replay dedup)
--
-- The mobile offline queue (mobile/src/services/offlineQueue.ts) replays a
-- write when the response to a successful submit is lost to a network drop —
-- it cannot tell "the server never got it" from "the server got it and the
-- reply never came back". Without a server-side dedup record, that replay
-- becomes a second incident/permit/checklist row. Clients now send an
-- X-Idempotency-Key header (stable per logical submission, reused on retry);
-- IdempotencyMiddleware (app/core/idempotency.py) looks it up here before
-- running the handler and replays the stored response on a repeat instead of
-- re-executing the write. See app/core/idempotency.py for the read/write path.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS idempotency_keys (
  id INT AUTO_INCREMENT PRIMARY KEY,
  idempotency_key VARCHAR(200) NOT NULL,
  request_path VARCHAR(255) NOT NULL,
  subject VARCHAR(100) NOT NULL COMMENT 'authenticated user id the key was scoped under',
  status_code INT NOT NULL,
  content_type VARCHAR(100) NOT NULL,
  response_body LONGTEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_idempotency_scope (idempotency_key, request_path, subject)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
