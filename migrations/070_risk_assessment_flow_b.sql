-- ─────────────────────────────────────────────────────────────────────────────
-- 070 · WF-01 Flow B — the Risk Assessment
--
-- The spec (Rev 5.0, 30 July 2026) describes two different journeys, and only
-- one of them existed. Flow A is the hazard register: a thing that is dangerous
-- gets spotted, controlled and closed. Flow B is a formal assessment of a
-- planned activity, ten steps, ending in a score that decides whether the work
-- can start at all.
--
-- What stood in for Flow B was `risk_reports` — one worker's sighting of one
-- hazard, scored L x S with the uplifts. That is a real thing and it stays, but
-- it is not an assessment: it covers one hazard rather than ten categories, it
-- is raised by whoever saw something rather than by the supervisor planning the
-- job, and nothing hangs a permit off it.
--
-- Two tables, because an assessment is a header and ten findings:
--
--   risk_assessments          the activity being assessed, its worst score, and
--                             the approval that lets work begin.
--   risk_assessment_hazards   one row per hazard category. The spec is emphatic
--                             that "a category cannot be silently skipped", so
--                             a row exists for all ten from the moment the
--                             assessment is created, each awaiting an answer.
--
-- The distinction the scoring turns on, and which nothing modelled before:
--
--   inherent  the score before controls — likelihood x severity, plus uplifts.
--   residual  the score after the chosen controls are applied.
--
-- The spec: "it is the residual score that decides whether work can start."
-- risk_reports only ever had raw and adjusted, and adjusted is *after uplifts*,
-- which raise the number. Blocking work on that is blocking on the wrong end of
-- the calculation.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS risk_assessments (
  id                     INT AUTO_INCREMENT PRIMARY KEY,
  organisation_id        INT NULL,

  -- What is being assessed. Step 01 SCOPE.
  activity               VARCHAR(255) NOT NULL,
  task_description       TEXT NULL,
  site_id                INT NULL,
  location_station_id    INT NULL,

  -- Where it is in the ten steps. Derived state is kept out of here on purpose;
  -- this is the record's own status, the way every other family works.
  status                 VARCHAR(40) NOT NULL DEFAULT 'scoping',

  -- Step 04. The four mandatory uplifts apply to the assessment as a whole,
  -- not per category — they describe the circumstances the work happens in.
  uplift_no_valid_rams   TINYINT DEFAULT 0,
  uplift_new_worker      TINYINT DEFAULT 0,
  uplift_night_shift     TINYINT DEFAULT 0,
  uplift_temporary_control TINYINT DEFAULT 0,
  uplift_total           INT DEFAULT 0,

  -- Steps 03-05. The worst category drives the assessment: an activity is as
  -- dangerous as its most dangerous part.
  inherent_score         INT NULL,
  adjusted_score         INT NULL,
  band                   VARCHAR(20) NULL,
  band_colour            VARCHAR(20) NULL,

  -- Step 08. What decides whether the work may begin.
  residual_score         INT NULL,
  residual_band          VARCHAR(20) NULL,
  blocks_work            TINYINT DEFAULT 0,
  approval_route         VARCHAR(40) NULL,
  approved_by            INT NULL,
  approved_at            DATETIME NULL,
  approval_notes         TEXT NULL,

  -- Step 09. Re-assessment triggers.
  review_frequency       VARCHAR(20) NULL,
  review_due_at          DATETIME NULL,
  reopened_reason        VARCHAR(255) NULL,
  reopened_at            DATETIME NULL,

  created_by             INT NULL,
  created_at             DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at             DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  archived_at            DATETIME NULL,

  INDEX idx_ra_org (organisation_id),
  INDEX idx_ra_status (status),
  INDEX idx_ra_review (review_due_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS risk_assessment_hazards (
  id                     INT AUTO_INCREMENT PRIMARY KEY,
  assessment_id          INT NOT NULL,
  organisation_id        INT NULL,

  -- Step 02. One row per category, created with the assessment so the ten are
  -- answerable but never skippable.
  category_key           VARCHAR(40) NOT NULL,
  category_name          VARCHAR(100) NOT NULL,
  category_id            INT NULL,

  -- Answered = somebody said yes or no. Null means still outstanding, which is
  -- what blocks the assessment from scoring.
  hazard_present         VARCHAR(3) NULL,
  description            TEXT NULL,

  -- Step 03. Inherent, before controls.
  likelihood             VARCHAR(50) NULL,
  severity               VARCHAR(50) NULL,
  inherent_score         INT NULL,

  -- Steps 06-07. The control and who owns it.
  control_hierarchy      VARCHAR(40) NULL,
  control_description    TEXT NULL,
  control_owner_id       INT NULL,
  control_due_date       DATE NULL,

  -- Step 08. After the control.
  residual_likelihood    VARCHAR(50) NULL,
  residual_severity      VARCHAR(50) NULL,
  residual_score         INT NULL,

  -- B -> A. The register entry this finding created, so a hazard identified in
  -- an assessment is tracked in one place rather than living only inside the
  -- document.
  hazard_id              INT NULL,

  created_at             DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at             DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  INDEX idx_rah_assessment (assessment_id),
  INDEX idx_rah_org (organisation_id),
  UNIQUE KEY uq_rah_assessment_category (assessment_id, category_key)
) ENGINE=InnoDB;
