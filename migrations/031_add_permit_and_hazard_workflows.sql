-- Migration: 031_add_permit_and_hazard_workflows
-- Purpose: Give Permit to Work (flow 6) and the Hazard register (flow 5) their own
--          role workflow, mirroring what 028/030 did for incidents and reports.
-- Depends on: 013_create_permits_to_work, 003_create_hazards
--
-- PURELY ADDITIVE. `permits_to_work.status` is left ALONE — the website dashboard
-- counts active permits with status='Active', so the new state machine rides on a
-- separate `workflow_status` column and only sets status='Active' when a manager
-- approves. Every added column is NULLable, so existing Pydantic responses are unchanged.

-- ═══════════════════════════════════════════════════════════════════════════════
-- 1. PERMIT TO WORK — Worker → Supervisor → Manager → Auditor workflow
-- ═══════════════════════════════════════════════════════════════════════════════
ALTER TABLE permits_to_work
    ADD COLUMN workflow_status VARCHAR(50) DEFAULT 'requested'
        COMMENT 'requested | acknowledged | approved | rejected',
    ADD COLUMN requested_by INT DEFAULT NULL,
    ADD COLUMN requested_at DATETIME DEFAULT NULL,
    ADD COLUMN acknowledged_by INT DEFAULT NULL,
    ADD COLUMN acknowledged_at DATETIME DEFAULT NULL,
    ADD COLUMN supervisor_notes TEXT DEFAULT NULL,
    ADD COLUMN approved_at DATETIME DEFAULT NULL,
    ADD COLUMN rejected_at DATETIME DEFAULT NULL,
    ADD COLUMN rejection_reason TEXT DEFAULT NULL,
    ADD COLUMN auditor_verified_by INT DEFAULT NULL,
    ADD COLUMN auditor_verified_at DATETIME DEFAULT NULL,
    ADD COLUMN verification_result VARCHAR(50) DEFAULT NULL
        COMMENT 'valid | invalid | not_displayed',
    ADD COLUMN verification_notes TEXT DEFAULT NULL;

ALTER TABLE permits_to_work
    ADD CONSTRAINT fk_ptw_requested_by
        FOREIGN KEY (requested_by) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_ptw_acknowledged_by
        FOREIGN KEY (acknowledged_by) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_ptw_auditor_verified_by
        FOREIGN KEY (auditor_verified_by) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE;

CREATE INDEX idx_ptw_workflow_status ON permits_to_work (workflow_status);

-- Pre-existing permits are seed/import rows that never went through the app workflow.
-- Treat anything already 'Active' as an approved permit; leave the rest as requested
-- so the supervisor queue is not flooded. Reversible by nulling workflow_status.
UPDATE permits_to_work
   SET workflow_status = CASE
           WHEN status = 'Active'   THEN 'approved'
           WHEN status = 'Rejected' THEN 'rejected'
           WHEN status = 'Closed'   THEN 'approved'
           ELSE 'acknowledged'
       END
 WHERE workflow_status = 'requested';

-- ═══════════════════════════════════════════════════════════════════════════════
-- 2. HAZARD REGISTER — log → review → auditor verification (flow 5)
-- ═══════════════════════════════════════════════════════════════════════════════
-- The `hazards` table is the organisation hazard register. These columns let a worker
-- or supervisor log a field hazard, a supervisor/manager move it through its control
-- lifecycle, and an auditor record that it is being managed — without disturbing the
-- website's catalog reads (hazard_name / severity / probability are untouched).
ALTER TABLE hazards
    ADD COLUMN register_status VARCHAR(50) DEFAULT 'open'
        COMMENT 'open | under_review | controlled | closed',
    ADD COLUMN description TEXT DEFAULT NULL,
    ADD COLUMN location_station_id INT DEFAULT NULL,
    ADD COLUMN logged_by INT DEFAULT NULL,
    ADD COLUMN logged_at DATETIME DEFAULT NULL,
    ADD COLUMN reviewed_by INT DEFAULT NULL,
    ADD COLUMN reviewed_at DATETIME DEFAULT NULL,
    ADD COLUMN review_notes TEXT DEFAULT NULL,
    ADD COLUMN controls TEXT DEFAULT NULL,
    ADD COLUMN auditor_verified_by INT DEFAULT NULL,
    ADD COLUMN auditor_verified_at DATETIME DEFAULT NULL,
    ADD COLUMN verification_notes TEXT DEFAULT NULL,
    ADD COLUMN gps_latitude VARCHAR(32) DEFAULT NULL,
    ADD COLUMN gps_longitude VARCHAR(32) DEFAULT NULL;

ALTER TABLE hazards
    ADD CONSTRAINT fk_hazards_logged_by
        FOREIGN KEY (logged_by) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_hazards_reviewed_by
        FOREIGN KEY (reviewed_by) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_hazards_auditor_verified_by
        FOREIGN KEY (auditor_verified_by) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_hazards_location_station
        FOREIGN KEY (location_station_id) REFERENCES working_stations (id)
        ON DELETE SET NULL ON UPDATE CASCADE;

CREATE INDEX idx_hazards_register_status ON hazards (register_status);

-- Existing catalog rows are reference data, not open field hazards. Mark them
-- 'controlled' so they do not appear as outstanding items in the review queue.
UPDATE hazards SET register_status = 'controlled' WHERE register_status = 'open';
