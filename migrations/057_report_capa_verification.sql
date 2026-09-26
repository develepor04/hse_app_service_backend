-- Migration: 057_report_capa_verification
-- Stage 06 VERIFY for near misses, unsafe acts and risk/hazard reports
-- Source: HSE_Workflow_Engine_Slide.pptx, stage 06
--
-- The same trio migration 054 added to incidents, for the three families the
-- report workflow factory serves. Deliberately separate from the existing
-- verification_notes column on these tables: that one belongs to the auditor's
-- post-closure review, while these record the manager's in-workflow sign-off
-- that the corrective action actually held.

ALTER TABLE near_misses
    ADD COLUMN capa_verified_by INT NULL COMMENT 'Employee who confirmed the CAPA worked',
    ADD COLUMN capa_verified_at DATETIME NULL COMMENT 'When stage 06 VERIFY was signed off',
    ADD COLUMN capa_verification_notes TEXT NULL COMMENT 'What was checked, and how',
    ADD COLUMN capa_verification_failures INT NOT NULL DEFAULT 0
        COMMENT 'Times a CAPA was verified as not effective and sent back to IMPROVE';

ALTER TABLE unsafe_acts
    ADD COLUMN capa_verified_by INT NULL COMMENT 'Employee who confirmed the CAPA worked',
    ADD COLUMN capa_verified_at DATETIME NULL COMMENT 'When stage 06 VERIFY was signed off',
    ADD COLUMN capa_verification_notes TEXT NULL COMMENT 'What was checked, and how',
    ADD COLUMN capa_verification_failures INT NOT NULL DEFAULT 0
        COMMENT 'Times a CAPA was verified as not effective and sent back to IMPROVE';

ALTER TABLE risk_reports
    ADD COLUMN capa_verified_by INT NULL COMMENT 'Employee who confirmed the CAPA worked',
    ADD COLUMN capa_verified_at DATETIME NULL COMMENT 'When stage 06 VERIFY was signed off',
    ADD COLUMN capa_verification_notes TEXT NULL COMMENT 'What was checked, and how',
    ADD COLUMN capa_verification_failures INT NOT NULL DEFAULT 0
        COMMENT 'Times a CAPA was verified as not effective and sent back to IMPROVE';
