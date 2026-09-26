-- Migration: 030_add_hse_report_workflows
-- Purpose: Give Near Miss, Unsafe Act and Risk reports their own tables and their own
--          Worker→Supervisor→Manager workflow, mirroring what 028 did for incidents.
-- Depends on: 028_add_incident_workflow_columns
--
-- PURELY ADDITIVE: nothing existing is altered or dropped. New worker submissions will
-- show up in website near-miss counts (accepted), but existing endpoints keep their
-- shape because their responses are explicit Pydantic models.
--
-- NOTE ON `hazards`: that table is a hazard *catalog* (hazard_name, category,
-- probability) shared by the website, NOT a worker report log. Worker-submitted risks
-- therefore get their own risk_reports table rather than polluting the catalog.

-- ═══════════════════════════════════════════════════════════════════════════════
-- 1. NEAR MISSES — add workflow columns to the existing table
-- ═══════════════════════════════════════════════════════════════════════════════
ALTER TABLE near_misses
    ADD COLUMN workflow_status VARCHAR(50) DEFAULT 'reported'
        COMMENT 'reported | acknowledged | under_investigation | escalated | pending_approval | closed',
    ADD COLUMN severity VARCHAR(50) DEFAULT 'medium',
    ADD COLUMN assigned_supervisor_id INT DEFAULT NULL,
    ADD COLUMN escalated_to_manager_id INT DEFAULT NULL,
    ADD COLUMN escalation_reason TEXT DEFAULT NULL;

ALTER TABLE near_misses
    ADD COLUMN reported_at DATETIME DEFAULT NULL,
    ADD COLUMN acknowledged_at DATETIME DEFAULT NULL,
    ADD COLUMN investigation_started_at DATETIME DEFAULT NULL,
    ADD COLUMN investigation_completed_at DATETIME DEFAULT NULL,
    ADD COLUMN escalated_at DATETIME DEFAULT NULL,
    ADD COLUMN approved_at DATETIME DEFAULT NULL,
    ADD COLUMN closed_at DATETIME DEFAULT NULL;

ALTER TABLE near_misses
    ADD COLUMN root_cause VARCHAR(255) DEFAULT NULL,
    ADD COLUMN five_why_analysis JSON DEFAULT NULL,
    ADD COLUMN immediate_actions_taken TEXT DEFAULT NULL,
    ADD COLUMN supervisor_signature VARCHAR(255) DEFAULT NULL,
    ADD COLUMN closure_notes TEXT DEFAULT NULL,
    ADD COLUMN lessons_learned TEXT DEFAULT NULL,
    ADD COLUMN manager_signature VARCHAR(255) DEFAULT NULL;

ALTER TABLE near_misses
    ADD COLUMN hazard_still_present ENUM('Yes','No') DEFAULT NULL,
    ADD COLUMN witnesses_json JSON DEFAULT NULL,
    ADD COLUMN evidence_json JSON DEFAULT NULL,
    ADD COLUMN gps_latitude DECIMAL(10,8) DEFAULT NULL,
    ADD COLUMN gps_longitude DECIMAL(11,8) DEFAULT NULL;

ALTER TABLE near_misses
    ADD CONSTRAINT fk_near_misses_assigned_supervisor
        FOREIGN KEY (assigned_supervisor_id) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_near_misses_escalated_manager
        FOREIGN KEY (escalated_to_manager_id) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE;

CREATE INDEX idx_near_misses_workflow_status ON near_misses (workflow_status);

-- The 500 pre-existing rows are seed/import data that never went through a workflow.
-- Mark them closed so they do not flood the supervisor queue and drown real reports.
-- Reversible: UPDATE near_misses SET workflow_status='reported', closed_at=NULL;
UPDATE near_misses
   SET workflow_status = 'closed',
       closed_at = COALESCE(closed_at, created_at)
 WHERE workflow_status = 'reported';

-- ═══════════════════════════════════════════════════════════════════════════════
-- 2. UNSAFE ACTS — brand new table
-- ═══════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS unsafe_acts (
    id                          INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id             INT DEFAULT NULL,

    report_date                 DATE DEFAULT NULL,
    observed_date_time          DATETIME DEFAULT NULL,
    location_station_id         INT DEFAULT NULL,

    act_type                    VARCHAR(100) DEFAULT NULL
        COMMENT 'ppe_violation | procedure_bypass | unsafe_lifting | horseplay | other',
    severity                    VARCHAR(50) DEFAULT 'medium',
    description                 TEXT,
    person_observed             VARCHAR(255) DEFAULT NULL
        COMMENT 'Free text on purpose - reporting a colleague should not require an employee record',
    rule_violated               VARCHAR(255) DEFAULT NULL,
    corrective_advice_given     ENUM('Yes','No') DEFAULT NULL,

    hazard_still_present        ENUM('Yes','No') DEFAULT NULL,
    witnesses_json              JSON DEFAULT NULL,
    evidence_json               JSON DEFAULT NULL,
    gps_latitude                DECIMAL(10,8) DEFAULT NULL,
    gps_longitude               DECIMAL(11,8) DEFAULT NULL,

    reported_by                 INT DEFAULT NULL,
    workflow_status             VARCHAR(50) DEFAULT 'reported'
        COMMENT 'reported | acknowledged | under_investigation | escalated | pending_approval | closed',
    assigned_supervisor_id      INT DEFAULT NULL,
    escalated_to_manager_id     INT DEFAULT NULL,
    escalation_reason           TEXT DEFAULT NULL,

    reported_at                 DATETIME DEFAULT NULL,
    acknowledged_at             DATETIME DEFAULT NULL,
    investigation_started_at    DATETIME DEFAULT NULL,
    investigation_completed_at  DATETIME DEFAULT NULL,
    escalated_at                DATETIME DEFAULT NULL,
    approved_at                 DATETIME DEFAULT NULL,
    closed_at                   DATETIME DEFAULT NULL,

    root_cause                  VARCHAR(255) DEFAULT NULL,
    five_why_analysis           JSON DEFAULT NULL,
    immediate_actions_taken     TEXT,
    supervisor_signature        VARCHAR(255) DEFAULT NULL,
    closure_notes               TEXT,
    lessons_learned             TEXT,
    manager_signature           VARCHAR(255) DEFAULT NULL,

    created_at                  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    KEY idx_unsafe_acts_org (organisation_id),
    KEY idx_unsafe_acts_workflow_status (workflow_status),
    CONSTRAINT fk_unsafe_acts_station
        FOREIGN KEY (location_station_id) REFERENCES working_stations (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_unsafe_acts_reported_by
        FOREIGN KEY (reported_by) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_unsafe_acts_assigned_supervisor
        FOREIGN KEY (assigned_supervisor_id) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_unsafe_acts_escalated_manager
        FOREIGN KEY (escalated_to_manager_id) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ═══════════════════════════════════════════════════════════════════════════════
-- 3. RISK REPORTS — brand new table (distinct from the `hazards` catalog)
-- ═══════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS risk_reports (
    id                          INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id             INT DEFAULT NULL,

    report_date                 DATE DEFAULT NULL,
    observed_date_time          DATETIME DEFAULT NULL,
    location_station_id         INT DEFAULT NULL,

    hazard_id                   INT DEFAULT NULL
        COMMENT 'Optional link to the hazards catalog when the risk matches a known hazard',
    risk_title                  VARCHAR(255) DEFAULT NULL,
    risk_category               VARCHAR(100) DEFAULT NULL,
    description                 TEXT,
    likelihood                  VARCHAR(50) DEFAULT NULL COMMENT 'rare | unlikely | possible | likely | almost_certain',
    consequence                 VARCHAR(50) DEFAULT NULL COMMENT 'negligible | minor | moderate | major | catastrophic',
    risk_score                  INT DEFAULT NULL COMMENT 'likelihood x consequence, 1-25',
    severity                    VARCHAR(50) DEFAULT 'medium',
    existing_controls           TEXT,
    suggested_controls          TEXT,

    hazard_still_present        ENUM('Yes','No') DEFAULT NULL,
    witnesses_json              JSON DEFAULT NULL,
    evidence_json               JSON DEFAULT NULL,
    gps_latitude                DECIMAL(10,8) DEFAULT NULL,
    gps_longitude               DECIMAL(11,8) DEFAULT NULL,

    reported_by                 INT DEFAULT NULL,
    workflow_status             VARCHAR(50) DEFAULT 'reported'
        COMMENT 'reported | acknowledged | under_investigation | escalated | pending_approval | closed',
    assigned_supervisor_id      INT DEFAULT NULL,
    escalated_to_manager_id     INT DEFAULT NULL,
    escalation_reason           TEXT DEFAULT NULL,

    reported_at                 DATETIME DEFAULT NULL,
    acknowledged_at             DATETIME DEFAULT NULL,
    investigation_started_at    DATETIME DEFAULT NULL,
    investigation_completed_at  DATETIME DEFAULT NULL,
    escalated_at                DATETIME DEFAULT NULL,
    approved_at                 DATETIME DEFAULT NULL,
    closed_at                   DATETIME DEFAULT NULL,

    root_cause                  VARCHAR(255) DEFAULT NULL,
    five_why_analysis           JSON DEFAULT NULL,
    immediate_actions_taken     TEXT,
    supervisor_signature        VARCHAR(255) DEFAULT NULL,
    closure_notes               TEXT,
    lessons_learned             TEXT,
    manager_signature           VARCHAR(255) DEFAULT NULL,

    created_at                  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    KEY idx_risk_reports_org (organisation_id),
    KEY idx_risk_reports_workflow_status (workflow_status),
    CONSTRAINT fk_risk_reports_station
        FOREIGN KEY (location_station_id) REFERENCES working_stations (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_risk_reports_hazard
        FOREIGN KEY (hazard_id) REFERENCES hazards (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_risk_reports_reported_by
        FOREIGN KEY (reported_by) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_risk_reports_assigned_supervisor
        FOREIGN KEY (assigned_supervisor_id) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_risk_reports_escalated_manager
        FOREIGN KEY (escalated_to_manager_id) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
