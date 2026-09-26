-- Migration: 013_create_permits_to_work
-- Table: permits_to_work
-- Depends on: permit_types, working_stations, employees

CREATE TABLE IF NOT EXISTS permits_to_work (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    permit_type_id          INT NOT NULL,
    date_issued             DATE NOT NULL,
    time_issued             TIME,
    location_station_id     INT,
    work_description        TEXT,
    duration_requested_hours INT,
    issued_by               INT,
    approved_by             INT,
    validity_start          DATETIME,
    validity_end            DATETIME,
    work_start_actual       DATETIME,
    work_end_actual         DATETIME,
    number_of_workers       INT,
    status                  VARCHAR(50),
    deviation_reported      ENUM('Yes', 'No') DEFAULT 'No',
    incident_occurred       ENUM('Yes', 'No') DEFAULT 'No',
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_ptw_permit_type
        FOREIGN KEY (permit_type_id) REFERENCES permit_types (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    CONSTRAINT fk_ptw_station
        FOREIGN KEY (location_station_id) REFERENCES working_stations (id)
        ON DELETE SET NULL ON UPDATE CASCADE,

    CONSTRAINT fk_ptw_issued_by
        FOREIGN KEY (issued_by) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE,

    CONSTRAINT fk_ptw_approved_by
        FOREIGN KEY (approved_by) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
