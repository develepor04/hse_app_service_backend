-- Migration: 063_audit_wf05_close_columns
-- Repairs the step 10 CLOSE columns for databases that ran 062 before it was fixed.
--
-- The original 062 named gps_latitude and gps_longitude in the same ALTER as the
-- close-out columns. Migration 044 had already added those two, so MySQL rejected
-- the statement as a duplicate column — and because an ALTER applies in full or
-- not at all, it took previous_audit_id, the three re_audit columns and closed_at
-- down with it. The runner logged it as "already in place" and moved on.
--
-- 062 no longer names the GPS columns, so a fresh database gets everything from
-- it and every statement below comes back as a duplicate and is skipped. An
-- already-migrated database gets the five columns it is missing.

ALTER TABLE audits
    ADD COLUMN previous_audit_id INT NULL COMMENT 'Same site and type — drives the repeat-finding flag';

ALTER TABLE audits
    ADD COLUMN re_audit_required TINYINT(1) NOT NULL DEFAULT 0;

ALTER TABLE audits
    ADD COLUMN re_audit_reason VARCHAR(160) NULL;

ALTER TABLE audits
    ADD COLUMN re_audit_due_date DATE NULL;

ALTER TABLE audits
    ADD COLUMN closed_at DATETIME NULL;
