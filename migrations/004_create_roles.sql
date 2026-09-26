-- Migration: 004_create_roles
-- Table: roles

CREATE TABLE IF NOT EXISTS roles (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    role_name       VARCHAR(100) NOT NULL,
    job_category    VARCHAR(100),
    authority_level TINYINT,
    permit_authority    ENUM('Yes', 'No') DEFAULT 'No',
    safety_signatory    ENUM('Yes', 'No') DEFAULT 'No',
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
