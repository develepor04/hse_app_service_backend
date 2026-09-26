-- Migration: 003_create_hazards
-- Table: hazards
-- Depends on: hazard_categories

CREATE TABLE IF NOT EXISTS hazards (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    category_id     INT NOT NULL,
    hazard_name     VARCHAR(255) NOT NULL,
    severity        VARCHAR(50),
    probability     VARCHAR(50),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_hazards_category
        FOREIGN KEY (category_id) REFERENCES hazard_categories (id)
        ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
