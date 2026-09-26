-- Migration: 007_create_training_programs
-- Table: training_programs

CREATE TABLE IF NOT EXISTS training_programs (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    training_name   VARCHAR(255) NOT NULL,
    duration_hours  INT,
    frequency       VARCHAR(50),
    certification   ENUM('Yes', 'No') DEFAULT 'No',
    expiry_months   INT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
