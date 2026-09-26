-- Rollback: relink worker01/supervisor01 to their original employee records
UPDATE users SET employee_id=601 WHERE id=15;  -- worker01
UPDATE users SET employee_id=602 WHERE id=16;  -- supervisor01
