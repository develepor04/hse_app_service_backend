-- Migration: 029_add_employee_photo
-- Table: employees
--
-- Stores the profile photo inline as a base64 data URI rather than a file path.
-- The API has no StaticFiles mount, so a file on disk could not be served over
-- HTTP, and an auth-protected file route is awkward for React Native's <Image>,
-- which does not send Authorization headers. Uploads are capped and downscaled
-- client-side, so rows stay small.

ALTER TABLE employees
    ADD COLUMN photo_base64 MEDIUMTEXT NULL AFTER full_name;
