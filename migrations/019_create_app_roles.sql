-- Migration: 019_create_app_roles
-- System-level roles for API authentication/authorisation (separate from HSE
-- operational roles in the `roles` table).

CREATE TABLE IF NOT EXISTS app_roles (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(50)  NOT NULL UNIQUE,
    label       VARCHAR(100) NOT NULL,
    description TEXT,
    level       TINYINT UNSIGNED NOT NULL DEFAULT 0,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
