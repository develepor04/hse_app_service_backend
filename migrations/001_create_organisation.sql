-- Migration: 001_create_organisation
-- Table: organisation

CREATE TABLE IF NOT EXISTS organisation (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    organisation_name       VARCHAR(255) NOT NULL,
    country                 VARCHAR(100),
    industry_sector         VARCHAR(100),
    number_of_employees     INT,
    headquarters_location   VARCHAR(255),
    parent_company          VARCHAR(255),
    iso_45001_status        VARCHAR(50),
    regulatory_authority    VARCHAR(255),
    establishment_date      DATE,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
