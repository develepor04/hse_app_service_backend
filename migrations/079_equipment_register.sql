-- ─────────────────────────────────────────────────────────────────────────────
-- 079 · Equipment/asset register (Module 4 — Assets & Operations)
--
-- The client's Assets_Sample_Data.xlsx (Assets_Register sheet) provides real
-- per-equipment maintenance/reliability data that this app had no table for —
-- unlocks MTBF, PM Compliance (proxy), and SCE Overdue Count, previously
-- flagged not computable in the Module 4 KPI spec for lack of any CMMS/asset
-- register data. See app/models/equipment.py.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS equipment (
  id INT AUTO_INCREMENT PRIMARY KEY,
  organisation_id INT NULL,
  equipment_code VARCHAR(50) NOT NULL,
  equipment_name VARCHAR(255) NOT NULL,
  equipment_type VARCHAR(120) NULL,
  location_station VARCHAR(50) NULL,
  installation_date DATE NULL,
  pm_interval_days INT NULL,
  last_pm_date DATE NULL,
  next_pm_due DATE NULL,
  operating_hours_ytd INT NULL,
  last_failure_date DATE NULL,
  mtbf_hours_estimated DECIMAL(10,2) NULL,
  safety_critical_sce TINYINT(1) NOT NULL DEFAULT 0,
  status VARCHAR(30) NULL,
  last_reviewed_at DATETIME NULL,
  last_verified_at DATETIME NULL,
  source_system VARCHAR(60) NULL DEFAULT 'server',
  jurisdiction VARCHAR(60) NULL,
  confidence_score DECIMAL(5,2) NULL,
  ai_generated TINYINT(1) NOT NULL DEFAULT 0,
  override_history LONGTEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY ix_equipment_org (organisation_id),
  KEY ix_equipment_code (equipment_code),
  KEY ix_equipment_type (equipment_type),
  KEY ix_equipment_status (status)
);
