-- Migration: 027_backfill_org_id_on_data_management
-- Existing data_imports and validation_logs rows have organisation_id = NULL
-- because they were written before tenant-scoping was added.
-- Backfill organisation_id from the uploading user's organisation wherever
-- the uploaded_by column matches a user's email address.

-- 1. data_imports → join on uploaded_by = users.email
UPDATE data_imports di
INNER JOIN users u ON u.email = di.uploaded_by
SET di.organisation_id = u.organisation_id
WHERE di.organisation_id IS NULL
  AND u.organisation_id IS NOT NULL;

-- 2. validation_logs have no uploaded_by, but each log was created in the
--    same request as a matching data_imports row (same file_name).
--    Propagate the now-populated organisation_id across via file_name.
UPDATE validation_logs vl
INNER JOIN (
    SELECT file_name, MIN(organisation_id) AS org_id
    FROM data_imports
    WHERE organisation_id IS NOT NULL
    GROUP BY file_name
) di ON di.file_name = vl.file_name
SET vl.organisation_id = di.org_id
WHERE vl.organisation_id IS NULL;
