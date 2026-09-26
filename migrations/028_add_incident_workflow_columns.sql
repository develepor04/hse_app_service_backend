-- Migration: 028_add_incident_workflow_columns
-- Purpose: Add role-based workflow columns to incidents table for Worker→Supervisor→Manager flow
-- Depends on: 014_create_incidents, 026_add_organisation_id_to_tenant_tables

-- ── Workflow Status ──────────────────────────────────────────────────────────
ALTER TABLE incidents
    ADD COLUMN workflow_status VARCHAR(50) DEFAULT 'reported'
        COMMENT 'reported | acknowledged | under_investigation | escalated | pending_approval | closed';

-- ── Assignment & Escalation ──────────────────────────────────────────────────
ALTER TABLE incidents
    ADD COLUMN assigned_supervisor_id INT DEFAULT NULL,
    ADD COLUMN escalated_to_manager_id INT DEFAULT NULL,
    ADD COLUMN escalation_reason TEXT DEFAULT NULL;

ALTER TABLE incidents
    ADD CONSTRAINT fk_incidents_assigned_supervisor
        FOREIGN KEY (assigned_supervisor_id) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE incidents
    ADD CONSTRAINT fk_incidents_escalated_manager
        FOREIGN KEY (escalated_to_manager_id) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE;

-- ── Timestamps for SLA tracking ──────────────────────────────────────────────
ALTER TABLE incidents
    ADD COLUMN reported_at DATETIME DEFAULT NULL,
    ADD COLUMN acknowledged_at DATETIME DEFAULT NULL,
    ADD COLUMN investigation_started_at DATETIME DEFAULT NULL,
    ADD COLUMN investigation_completed_at DATETIME DEFAULT NULL,
    ADD COLUMN escalated_at DATETIME DEFAULT NULL,
    ADD COLUMN approved_at DATETIME DEFAULT NULL,
    ADD COLUMN closed_at DATETIME DEFAULT NULL;

-- ── Manager closure fields ───────────────────────────────────────────────────
ALTER TABLE incidents
    ADD COLUMN closure_notes TEXT DEFAULT NULL,
    ADD COLUMN regulatory_notified ENUM('Yes', 'No') DEFAULT 'No',
    ADD COLUMN lessons_learned TEXT DEFAULT NULL,
    ADD COLUMN communicated_to_teams ENUM('Yes', 'No') DEFAULT 'No',
    ADD COLUMN manager_signature VARCHAR(255) DEFAULT NULL;

-- ── Worker report extra fields ───────────────────────────────────────────────
ALTER TABLE incidents
    ADD COLUMN anyone_injured ENUM('Yes', 'No') DEFAULT 'No',
    ADD COLUMN injured_person_name VARCHAR(255) DEFAULT NULL,
    ADD COLUMN injured_body_part VARCHAR(255) DEFAULT NULL,
    ADD COLUMN hazard_still_present ENUM('Yes', 'No') DEFAULT 'No',
    ADD COLUMN witnesses_json JSON DEFAULT NULL
        COMMENT 'Array of witness names: ["name1", "name2"]',
    ADD COLUMN evidence_json JSON DEFAULT NULL
        COMMENT 'Array of photo/video URLs',
    ADD COLUMN gps_latitude DECIMAL(10, 8) DEFAULT NULL,
    ADD COLUMN gps_longitude DECIMAL(11, 8) DEFAULT NULL;

-- ── Supervisor investigation fields ──────────────────────────────────────────
ALTER TABLE incidents
    ADD COLUMN five_why_analysis JSON DEFAULT NULL
        COMMENT 'Array of 5-why steps: [{why: "...", answer: "..."}]',
    ADD COLUMN immediate_actions_taken TEXT DEFAULT NULL,
    ADD COLUMN supervisor_signature VARCHAR(255) DEFAULT NULL,
    ADD COLUMN severity_classification VARCHAR(50) DEFAULT NULL
        COMMENT 'LTI | MTI | First Aid | Near Miss';

-- ── Backfill existing rows ───────────────────────────────────────────────────
UPDATE incidents SET workflow_status = 'closed' WHERE investigation_status = 'Completed';
UPDATE incidents SET workflow_status = 'under_investigation' WHERE investigation_status != 'Completed' AND investigation_status IS NOT NULL AND workflow_status = 'reported';
UPDATE incidents SET reported_at = incident_date_time WHERE reported_at IS NULL AND incident_date_time IS NOT NULL;
