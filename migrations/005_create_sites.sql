-- Migration: 005_create_sites
-- Table: sites

CREATE TABLE IF NOT EXISTS sites (
    id                          INT AUTO_INCREMENT PRIMARY KEY,
    site_name                   VARCHAR(255) NOT NULL,
    address                     VARCHAR(255),
    postcode                    VARCHAR(20),
    city                        VARCHAR(100),
    type                        VARCHAR(100),
    operational_status          VARCHAR(50),
    number_of_working_stations  INT,
    capacity                    INT,
    primary_products            VARCHAR(255),
    hazard_classification       VARCHAR(50),
    created_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
