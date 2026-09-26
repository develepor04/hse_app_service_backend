-- Migration: 017_create_capa_actions
-- Table: capa_actions
-- Depends on: incidents, employees

CREATE TABLE IF NOT EXISTS capa_actions (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    incident_id             INT,
    action_type             VARCHAR(100),
    description             TEXT,
    root_cause_addressed    VARCHAR(255),
    responsible_person_id   INT,
    due_date                DATE,
    status                  VARCHAR(50),
    effectiveness_rating    TINYINT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_capa_incident
        FOREIGN KEY (incident_id) REFERENCES incidents (id)
        ON DELETE SET NULL ON UPDATE CASCADE,

    CONSTRAINT fk_capa_responsible
        FOREIGN KEY (responsible_person_id) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
