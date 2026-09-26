-- Migration: 061_notification_targeting
-- Per-employee notifications
--
-- `notifications` had target_type ENUM('all','specific') but the only "specific"
-- target was an invite id, and NotificationRepository.get_for_org returns every
-- row in the organisation to every user regardless. So a CAPA assignment
-- notification naming one person was delivered to everyone, and the person who
-- actually had to act got no more signal than anybody else.
--
-- Step 05 of the CAPA lifecycle ("Owner notified... appears on their dashboard")
-- and the whole escalation chain (owner at 75%, supervisor at 90%, Safety
-- Manager at 100%) depend on a notification reaching one named person.

ALTER TABLE notifications
    ADD COLUMN target_employee_id INT NULL
        COMMENT 'Employee this is addressed to. NULL with target_type=all means everyone.',
    ADD COLUMN category VARCHAR(40) NULL
        COMMENT 'capa_assigned | capa_escalation | capa_review_due | ... — lets a client filter',
    ADD COLUMN subject_ref VARCHAR(40) NULL
        COMMENT 'The record it is about, e.g. CAPA-000230';

CREATE INDEX idx_notifications_target ON notifications (organisation_id, target_employee_id);
