-- ─────────────────────────────────────────────────────────────────────────────
-- 078 · Fields Module 5 (Contractors & Vendors) needs that the WF-08 registry
-- didn't carry, plus a real monthly hours-worked log
--
-- contractor_companies already covers prequalification/insurance/LTIFR-TRIR
-- for the mobile RAMS-scoring workflow, but the client's own Module 5 KPI
-- spec (contractor register + sample data) also expects service type,
-- contract dates, ISO 45001 status and last safety-audit date per company —
-- none of which existed. Added nullable/additive, no existing row affected.
--
-- Contractor Hours: nothing in the schema tracked actual hours worked per
-- contractor per month — the web Vendors page previously approximated
-- "Contractor Exposure Hours" from PermitToWork durations. Contractor TRIR
-- (injuries x 200,000 / hours) needs the real figure, so a proper log table.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE contractor_companies
  ADD COLUMN service_type VARCHAR(120) NULL AFTER company_name,
  ADD COLUMN contract_start_date DATE NULL AFTER service_type,
  ADD COLUMN contract_end_date DATE NULL AFTER contract_start_date,
  ADD COLUMN iso_45001_certified TINYINT(1) NULL AFTER contract_end_date,
  ADD COLUMN last_safety_audit_date DATE NULL AFTER iso_45001_certified;

-- Columns from AiIsmsMetadataMixin (app/models/aiisms_mixin.py) — every
-- AI-ISMS entity carries these; contractor_companies/workers already do.
CREATE TABLE IF NOT EXISTS contractor_hours (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organisation_id INT NULL,
  contractor_company_id INT NOT NULL,
  period_year INT NOT NULL,
  period_month INT NOT NULL,
  hours_worked INT NOT NULL DEFAULT 0,
  last_reviewed_at DATETIME NULL,
  last_verified_at DATETIME NULL,
  source_system VARCHAR(60) NULL DEFAULT 'server',
  jurisdiction VARCHAR(60) NULL,
  confidence_score DECIMAL(5,2) NULL,
  ai_generated TINYINT(1) NOT NULL DEFAULT 0,
  override_history LONGTEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_contractor_hours_period (contractor_company_id, period_year, period_month),
  KEY ix_contractor_hours_org (organisation_id),
  CONSTRAINT fk_contractor_hours_company FOREIGN KEY (contractor_company_id)
    REFERENCES contractor_companies(id)
);
