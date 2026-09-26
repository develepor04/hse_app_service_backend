-- Migration: 006_create_permit_types
-- Table: permit_types

CREATE TABLE IF NOT EXISTS permit_types (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    permit_type_name        VARCHAR(255) NOT NULL,
    risk_level              VARCHAR(50),
    validity_period_hours   INT,
    concurrent_limit        INT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
