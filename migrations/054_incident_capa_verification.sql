-- Migration: 054_incident_capa_verification
-- Stage 06 VERIFY — "Confirm it worked"
-- Source: HSE_Workflow_Engine_Slide.pptx, stage 06
--
-- The manager already had one sign-off (approve-investigation), but that
-- approves the root cause analysis, not the fix. The workflow slide puts
-- IMPROVE at 05 and VERIFY at 06 precisely because those are different
-- questions: "is this the right corrective action" and "did it hold".
--
-- These columns record the second answer. They are deliberately separate from
-- auditor_verified_by/at/verification_notes, which belong to the auditor's
-- post-closure close-out review and are not part of the workflow.

ALTER TABLE incidents
    ADD COLUMN capa_verified_by INT NULL COMMENT 'Employee who confirmed the CAPA worked',
    ADD COLUMN capa_verified_at DATETIME NULL COMMENT 'When stage 06 VERIFY was signed off',
    ADD COLUMN capa_verification_notes TEXT NULL COMMENT 'What was checked, and how',
    ADD COLUMN capa_verification_failures INT NOT NULL DEFAULT 0
        COMMENT 'Times a CAPA was verified as not effective and sent back to IMPROVE';

ALTER TABLE incidents
    ADD CONSTRAINT fk_incidents_capa_verified_by
        FOREIGN KEY (capa_verified_by) REFERENCES employees(id);

CREATE INDEX idx_incidents_capa_verified_at ON incidents (capa_verified_at);
