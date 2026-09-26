-- Audit Trail & System Logs (client diagram: Web Portal control-center item)
-- Records admin-level mutating actions (org setup, users/roles, settings) so the
-- Audit Trail page can show real who/what/when instead of an empty stub.

CREATE TABLE IF NOT EXISTS audit_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id INT NULL,
    employee_id INT NULL,
    action VARCHAR(100) NOT NULL,
    module VARCHAR(100) NOT NULL,
    record_id VARCHAR(100) NULL,
    previous_value TEXT NULL,
    new_value TEXT NULL,
    ip_address VARCHAR(64) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_audit_logs_org (organisation_id),
    INDEX idx_audit_logs_created (created_at),
    CONSTRAINT fk_audit_logs_org FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE CASCADE,
    CONSTRAINT fk_audit_logs_employee FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
