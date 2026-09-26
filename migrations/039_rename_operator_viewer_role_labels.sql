-- Migration: 039_rename_operator_viewer_role_labels
-- Rename the display labels for the 'operator' and 'viewer' app roles to match
-- the terminology used across the product: Worker and Auditor.

UPDATE app_roles SET label = 'Worker'   WHERE name = 'operator';
UPDATE app_roles SET label = 'Auditor'  WHERE name = 'viewer';
