-- Migration: 016_create_safety_walks
-- Table: safety_walks
-- Depends on: working_stations, employees

CREATE TABLE IF NOT EXISTS safety_walks (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    inspection_date_time    DATETIME,
    location_station_id     INT,
    inspector_id            INT,
    inspection_type         VARCHAR(100),
    issues_found            INT DEFAULT 0,
    critical_issues         INT DEFAULT 0,
    housekeeping_rating     TINYINT,
    compliance_rating       TINYINT,
    follow_up_required      ENUM('Yes', 'No') DEFAULT 'No',
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_sw_station
        FOREIGN KEY (location_station_id) REFERENCES working_stations (id)
        ON DELETE SET NULL ON UPDATE CASCADE,

    CONSTRAINT fk_sw_inspector
        FOREIGN KEY (inspector_id) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
