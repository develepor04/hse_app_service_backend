-- Migration: 008_create_policies
-- Table: policies

CREATE TABLE IF NOT EXISTS policies (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    policy_name     VARCHAR(255) NOT NULL,
    category        VARCHAR(100),
    issue_date      DATE,
    owner           VARCHAR(100),
    status          VARCHAR(50),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
