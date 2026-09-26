-- Migration: 014_create_incidents
-- Table: incidents
-- Depends on: working_stations, hazards, employees

CREATE TABLE IF NOT EXISTS incidents (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    report_date             DATE,
    incident_date_time      DATETIME,
    location_station_id     INT,
    incident_type           VARCHAR(100),
    severity                VARCHAR(50),
    number_persons_involved INT,
    description             TEXT,
    immediate_cause         VARCHAR(255),
    root_cause              VARCHAR(255),
    hazard_id               INT,
    permit_active           ENUM('Yes', 'No') DEFAULT NULL,
    control_failure         ENUM('Yes', 'No') DEFAULT NULL,
    reported_by             INT,
    investigation_status    VARCHAR(50),
    capa_generated          ENUM('Yes', 'No') DEFAULT 'No',
    days_away               INT DEFAULT 0,
    root_cause_category     VARCHAR(100),
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_incidents_station
        FOREIGN KEY (location_station_id) REFERENCES working_stations (id)
        ON DELETE SET NULL ON UPDATE CASCADE,

    CONSTRAINT fk_incidents_hazard
        FOREIGN KEY (hazard_id) REFERENCES hazards (id)
        ON DELETE SET NULL ON UPDATE CASCADE,

    CONSTRAINT fk_incidents_reported_by
        FOREIGN KEY (reported_by) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
