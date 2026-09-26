-- Migration: 018_create_shift_schedule
-- Table: shift_schedule
-- Depends on: employees, working_stations

CREATE TABLE IF NOT EXISTS shift_schedule (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    employee_id             INT NOT NULL,
    shift_date              DATE NOT NULL,
    shift_type              VARCHAR(50),
    shift_start             TIME,
    shift_end               TIME,
    actual_hours_worked     DECIMAL(4, 1),
    station_id              INT,
    supervisor_id           INT,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_shift_employee
        FOREIGN KEY (employee_id) REFERENCES employees (id)
        ON DELETE CASCADE ON UPDATE CASCADE,

    CONSTRAINT fk_shift_station
        FOREIGN KEY (station_id) REFERENCES working_stations (id)
        ON DELETE SET NULL ON UPDATE CASCADE,

    CONSTRAINT fk_shift_supervisor
        FOREIGN KEY (supervisor_id) REFERENCES employees (id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
