-- Auditor spec gaps from HSEIQ_Role_Checklist.pdf.
--
-- 1. "Compliance Checklist Submission" specifies a Shift field (Morning/Afternoon/
--    Night). The audits table had site_id/site_name but no shift.
-- 2. "Incident Close-Out Review" lets the auditor add an audit sign-off note against
--    an incident. permits_to_work and hazards already carry auditor_verified_by /
--    auditor_verified_at / verification_notes; incidents did not.

ALTER TABLE audits
  ADD COLUMN shift VARCHAR(20) NULL AFTER department;

ALTER TABLE incidents
  ADD COLUMN auditor_verified_by INT NULL,
  ADD COLUMN auditor_verified_at DATETIME NULL,
  ADD COLUMN verification_notes TEXT NULL;
