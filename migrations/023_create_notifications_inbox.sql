-- Migration: 023_create_notifications_inbox
-- Creates the notifications table (with organisation scoping) and
-- the notification_reads junction table for per-user read/unread tracking.

CREATE TABLE IF NOT EXISTS notifications (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id     INT NULL,
    title               VARCHAR(255) NOT NULL,
    message             TEXT NOT NULL,
    type                ENUM('info','success','warning','maintenance','announcement') NOT NULL DEFAULT 'info',
    target_type         ENUM('all','specific') NOT NULL DEFAULT 'all',
    target_invite_id    INT NULL,
    status              ENUM('draft','sent','failed') NOT NULL DEFAULT 'draft',
    email_sent_count    INT NOT NULL DEFAULT 0,
    sent_at             DATETIME NULL,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_notifications_org (organisation_id),
    INDEX idx_notifications_status (status),
    CONSTRAINT fk_notifications_org
        FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE CASCADE,
    CONSTRAINT fk_notifications_invite
        FOREIGN KEY (target_invite_id) REFERENCES organisation_invite(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Per-user read tracking
CREATE TABLE IF NOT EXISTS notification_reads (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    notification_id     INT NOT NULL,
    user_id             INT NOT NULL,
    read_at             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_notif_user (notification_id, user_id),
    INDEX idx_nr_user (user_id),
    CONSTRAINT fk_nr_notification
        FOREIGN KEY (notification_id) REFERENCES notifications(id) ON DELETE CASCADE,
    CONSTRAINT fk_nr_user
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
