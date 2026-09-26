CREATE TABLE IF NOT EXISTS organisation_invite (
    id          INT NOT NULL AUTO_INCREMENT,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    organisation_name VARCHAR(255) NOT NULL,
    admin_name        VARCHAR(255) NOT NULL,
    admin_email       VARCHAR(255) NOT NULL,
    temp_password     VARCHAR(255) NOT NULL,
    status            ENUM('pending', 'accepted', 'expired') NOT NULL DEFAULT 'pending',
    PRIMARY KEY (id),
    INDEX ix_organisation_invite_id (id),
    INDEX ix_organisation_invite_admin_email (admin_email)
);
