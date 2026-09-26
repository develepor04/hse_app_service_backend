-- Migration: 015_create_near_misses
-- Table: near_misses
-- Depends on: working_stations, hazards, employees

CREATE TABLE IF NOT EXISTS near_misses (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    report_date             DATE,
    event_date_time         DATETIME,
    location_station_id     INT,
    description             TEXT,
    potential_consequence   VARCHAR(255),
    hazard_id               INT,
    underlying_cause        VARCHAR(255),
    control_failure         ENUM('Yes', 'No') DEFAULT NULL,
    reported_by             INT,
    capa_escalation         ENUM('Yes', 'No') DEFAULT 'No',
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_nm_station
        FOREIGN KEY (location_station_id) REFERENCES working_stations (id)
        ON DELETE SET NULL ON UPDATE CASCADE,

    CONSTRAINT fk_nm_hazard
        FOREIGN KEY (hazard_id) REFERENCES hazards (id)
        ON DELETE SET NULL ON UPDATE CASCADE,

    CONSTRAINT fk_nm_reported_by
        FOREIGN KEY (reported_by) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
