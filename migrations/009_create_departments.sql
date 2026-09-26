-- Migration: 009_create_departments
-- Table: departments
-- Depends on: sites
-- Note: manager_id FK to employees is added in migration 012 to break the
--       circular dependency between departments and employees.

CREATE TABLE IF NOT EXISTS departments (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    site_id             INT NOT NULL,
    department_name     VARCHAR(255) NOT NULL,
    manager_id          INT DEFAULT NULL,
    number_of_teams     INT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_departments_site
        FOREIGN KEY (site_id) REFERENCES sites (id)
        ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
