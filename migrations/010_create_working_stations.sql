-- Migration: 010_create_working_stations
-- Table: working_stations
-- Depends on: sites, hazards

CREATE TABLE IF NOT EXISTS working_stations (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    station_name            VARCHAR(255) NOT NULL,
    site_id                 INT NOT NULL,
    department              VARCHAR(255),
    zone_classification     VARCHAR(100),
    primary_hazard_id       INT,
    staffing_requirement    INT,
    equipment_list          TEXT,
    permit_types_required   VARCHAR(255),
    access_restrictions     VARCHAR(255),
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_ws_site
        FOREIGN KEY (site_id) REFERENCES sites (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,

    CONSTRAINT fk_ws_hazard
        FOREIGN KEY (primary_hazard_id) REFERENCES hazards (id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
