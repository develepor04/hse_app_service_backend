-- Migration: 020_create_users
-- Application users for authentication (may be linked to an Employee record).
-- Depends on: app_roles, employees

CREATE TABLE IF NOT EXISTS users (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    username        VARCHAR(100) NOT NULL UNIQUE,
    email           VARCHAR(255) NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    app_role_id     INT NOT NULL,
    employee_id     INT DEFAULT NULL,
    is_active       TINYINT(1) NOT NULL DEFAULT 1,
    last_login      DATETIME DEFAULT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_users_app_role
        FOREIGN KEY (app_role_id) REFERENCES app_roles (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    CONSTRAINT fk_users_employee
        FOREIGN KEY (employee_id) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
