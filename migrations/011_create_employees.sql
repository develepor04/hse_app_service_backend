-- Migration: 011_create_employees
-- Table: employees
-- Depends on: roles, departments
-- Note: manager_id is a self-referential FK (employee's manager is also an employee).

CREATE TABLE IF NOT EXISTS employees (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    full_name               VARCHAR(255) NOT NULL,
    date_of_birth           DATE,
    gender                  CHAR(1),
    employment_type         VARCHAR(50),
    employment_start_date   DATE,
    role_id                 INT,
    department_id           INT,
    shift_pattern           VARCHAR(50),
    manager_id              INT DEFAULT NULL,
    induction_date          DATE,
    active_status           VARCHAR(20) DEFAULT 'Active',
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_employees_role
        FOREIGN KEY (role_id) REFERENCES roles (id)
        ON DELETE SET NULL ON UPDATE CASCADE,

    CONSTRAINT fk_employees_department
        FOREIGN KEY (department_id) REFERENCES departments (id)
        ON DELETE SET NULL ON UPDATE CASCADE,

    CONSTRAINT fk_employees_manager
        FOREIGN KEY (manager_id) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
