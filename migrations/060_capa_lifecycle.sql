-- Migration: 060_capa_lifecycle
-- WF-04 Corrective & Preventive Action Management — the full ten-step lifecycle
-- Source: HSE_CAPA_Lifecycle.pdf Rev 5.0, aligned to EHSERA-ISMS-AO-2026-v1.0
--
-- What existed before this: a CAPA was a description, an owner, a due date and a
-- status that went Open -> Completed. Marking it complete advanced the parent
-- record straight to verification. The document's whole point is the opposite —
-- "marking an action complete does not close it" — and none of the machinery
-- that makes that true was present. No plan, no success criteria, no evidence,
-- no closure checks, no independent review, no effectiveness reviews, and no
-- escalation, so an action could age quietly forever and close on one click.
--
-- Everything here is additive. The existing columns keep their meaning and the
-- fourteen aggregate queries that read incident_id, status and due_date are
-- untouched.

-- ── Step 01 RAISE · reference number, and the polymorphic link ───────────────
-- capa_ref is the human-facing identifier the document expects the system to
-- generate at creation ("Generates the reference number").
ALTER TABLE capa_actions
    ADD COLUMN capa_ref VARCHAR(30) NULL COMMENT 'CAPA-000123, generated at creation',
    ADD COLUMN source VARCHAR(30) NULL
        COMMENT 'incident | audit | risk_assessment | inspection | regulatory | proactive',
    ADD COLUMN raised_by INT NULL COMMENT 'Employee who raised the action';

-- ── Step 03 PLAN · the action plan and its success criteria ─────────────────
-- success_criteria is what step 08 CHECK 1 measures the evidence against. It is
-- the single most load-bearing field in the document and had no column at all.
ALTER TABLE capa_actions
    ADD COLUMN action_plan TEXT NULL COMMENT 'The specific action and resources needed',
    ADD COLUMN success_criteria TEXT NULL COMMENT 'How we will know it worked — mandatory to plan',
    ADD COLUMN action_category VARCHAR(30) NULL
        COMMENT 'physical_fix | procedure_change | training | inspection | test | other',
    -- "CAPA by hierarchy of control" appears on the workflow slide and in the
    -- stage 05 description, but nothing recorded which level a control sat at.
    ADD COLUMN hierarchy_level VARCHAR(20) NULL
        COMMENT 'elimination | substitution | engineering | administrative | ppe',
    ADD COLUMN planned_at DATETIME NULL,
    ADD COLUMN plan_approved_by INT NULL COMMENT 'Manager — required for High and Critical bands',
    ADD COLUMN plan_approved_at DATETIME NULL;

-- ── Step 05 ASSIGN / Step 06 DO ─────────────────────────────────────────────
ALTER TABLE capa_actions
    ADD COLUMN assigned_by INT NULL,
    ADD COLUMN assigned_at DATETIME NULL,
    ADD COLUMN started_at DATETIME NULL,
    -- The supervisor's halfway confirmation that progress is real. One of the
    -- four points the document says cannot be bypassed.
    ADD COLUMN interim_check_by INT NULL,
    ADD COLUMN interim_check_at DATETIME NULL,
    ADD COLUMN interim_check_notes TEXT NULL;

-- ── Step 07 / 08 · evidence, validation and independent review ──────────────
ALTER TABLE capa_actions
    ADD COLUMN evidence_submitted_at DATETIME NULL,
    ADD COLUMN evidence_submitted_by INT NULL,
    ADD COLUMN independent_review_by INT NULL,
    ADD COLUMN independent_review_at DATETIME NULL,
    ADD COLUMN independent_review_result VARCHAR(20) NULL COMMENT 'confirmed | rejected',
    ADD COLUMN independent_review_notes TEXT NULL,
    -- The result of the three closure checks the last time they were run, so a
    -- rejection can name the specific reason rather than "not allowed".
    ADD COLUMN closure_checks_json JSON NULL;

-- ── Step 10 CLOSE · approval and archive ────────────────────────────────────
ALTER TABLE capa_actions
    ADD COLUMN closed_by INT NULL COMMENT 'Safety Manager — the final gate',
    ADD COLUMN closed_at DATETIME NULL,
    ADD COLUMN closure_notes TEXT NULL,
    ADD COLUMN lesson_learned TEXT NULL,
    -- Set once approved. The audit trail is locked against further edits, which
    -- is what "archives" means in step 10.
    ADD COLUMN is_locked TINYINT(1) NOT NULL DEFAULT 0,
    ADD COLUMN reopened_count INT NOT NULL DEFAULT 0;

-- ── The escalation timer chain, and weekly re-scoring ───────────────────────
-- escalation_level records the highest threshold already fired so the hourly job
-- is idempotent — without it every run would re-notify everyone.
ALTER TABLE capa_actions
    ADD COLUMN escalation_level INT NOT NULL DEFAULT 0
        COMMENT 'Highest elapsed-time threshold fired: 0 | 50 | 75 | 90 | 100 | 110',
    ADD COLUMN last_escalated_at DATETIME NULL,
    ADD COLUMN last_rescored_at DATETIME NULL,
    ADD COLUMN systemic_flag TINYINT(1) NOT NULL DEFAULT 0
        COMMENT '3+ actions on this root cause within 6 months';

CREATE INDEX idx_capa_ref ON capa_actions (capa_ref);
CREATE INDEX idx_capa_due_status ON capa_actions (due_date, status);
CREATE INDEX idx_capa_owner_status ON capa_actions (responsible_person_id, status);


-- ── Evidence · step 07 ──────────────────────────────────────────────────────
-- A table rather than a column because an action can need several pieces (the
-- photo AND the revised document), and because each piece carries its own
-- validation verdict. capa_actions.evidence_required only ever held a sentence
-- describing what ought to be produced.
CREATE TABLE IF NOT EXISTS capa_evidence (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id     INT NULL,
    capa_id             INT NOT NULL,

    -- photo | document | training_record | test_report | inspection_confirmation
    evidence_type       VARCHAR(40) NOT NULL,
    file_url            VARCHAR(500) NULL COMMENT 'Path under /uploads, when a file was attached',
    description         TEXT NULL,

    -- When the thing being evidenced actually happened. CHECK 2 compares this
    -- against the action's created_at to block the most common false closure:
    -- attaching a document that already existed.
    evidence_date       DATETIME NULL,

    uploaded_by         INT NULL,
    uploaded_at         DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- accepted | rejected. Set by the automatic validation, not by a person.
    validation_result   VARCHAR(20) NULL,
    rejection_reason    VARCHAR(255) NULL,

    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_capa_evidence_capa (capa_id, validation_result)
);


-- ── Progress notes · step 06 ────────────────────────────────────────────────
-- "Long-running actions need interim notes." Also the record the 75% reminder
-- checks against to decide whether progress has actually been recorded.
CREATE TABLE IF NOT EXISTS capa_progress_notes (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id     INT NULL,
    capa_id             INT NOT NULL,
    note                TEXT NOT NULL,
    percent_complete    INT NULL,
    author_id           INT NULL,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_capa_progress_capa (capa_id, created_at)
);


-- ── Effectiveness reviews · step 09 ─────────────────────────────────────────
-- Scheduled at closure, one row per review point. The document's three questions
-- are stored as three answers rather than one verdict, because "the control is
-- still in place but the root cause recurred" is a different failure from "the
-- control was removed" and reopening on a single boolean would lose that.
CREATE TABLE IF NOT EXISTS capa_effectiveness_reviews (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id     INT NULL,
    capa_id             INT NOT NULL,

    review_point        INT NOT NULL COMMENT 'Days after closure: 30 | 60 | 90',
    due_at              DATETIME NOT NULL,

    -- pending | passed | failed
    result              VARCHAR(20) NOT NULL DEFAULT 'pending',
    has_recurred        TINYINT(1) NULL COMMENT 'Has the same issue happened again',
    control_in_place    TINYINT(1) NULL COMMENT 'Is the control still physically there',
    root_cause_addressed TINYINT(1) NULL COMMENT 'Was the underlying cause actually fixed',
    notes               TEXT NULL,

    reviewed_by         INT NULL,
    reviewed_at         DATETIME NULL,
    -- Set when this review reopened the action, so the trail shows which check
    -- caught it.
    triggered_reopen    TINYINT(1) NOT NULL DEFAULT 0,

    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_capa_review_due (due_at, result),
    INDEX idx_capa_review_capa (capa_id, review_point)
);


-- ── Backfill ────────────────────────────────────────────────────────────────
-- subject_family was added by migration 056 and backfilled once, but the
-- creation path never set it, so every CAPA raised since then reads NULL and is
-- invisible to any query using the polymorphic link. Repair the existing rows.
UPDATE capa_actions
   SET subject_family = 'incident',
       subject_id     = incident_id
 WHERE incident_id IS NOT NULL
   AND (subject_family IS NULL OR subject_id IS NULL);

-- Reference numbers for everything already in the table.
UPDATE capa_actions
   SET capa_ref = CONCAT('CAPA-', LPAD(id, 6, '0'))
 WHERE capa_ref IS NULL;

-- Historical rows came from incident investigations by definition — that was the
-- only path that created one.
UPDATE capa_actions
   SET source = 'incident'
 WHERE source IS NULL
   AND incident_id IS NOT NULL;

-- Legacy 'Completed' rows are terminal and already counted as closed by every
-- open-CAPA filter. Stamp closed_at so the ageing report and the effectiveness
-- scheduler have a date to work from, and lock them: they predate the evidence
-- and review machinery and must not be dragged into it retrospectively.
UPDATE capa_actions
   SET closed_at = COALESCE(closed_at, updated_at, created_at),
       is_locked = 1
 WHERE LOWER(status) IN ('completed', 'closed', 'verified', 'done')
   AND closed_at IS NULL;
