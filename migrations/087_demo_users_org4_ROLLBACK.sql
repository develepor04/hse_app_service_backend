-- Rollback: restore demo users/employees to organisation 1
UPDATE users SET organisation_id=1 WHERE id=15;  -- worker01
UPDATE users SET organisation_id=1 WHERE id=16;  -- supervisor01
UPDATE users SET organisation_id=1 WHERE id=17;  -- auditor01
UPDATE users SET organisation_id=1 WHERE id=18;  -- manager01
UPDATE employees SET organisation_id=1, department_id=1, role_id=11 WHERE id=601;  -- Worker One
UPDATE employees SET organisation_id=1, department_id=1, role_id=4 WHERE id=602;  -- Supervisor One
UPDATE employees SET organisation_id=1, department_id=NULL, role_id=NULL WHERE id=612;  -- Auditor One
UPDATE employees SET organisation_id=1, department_id=NULL, role_id=NULL WHERE id=625;  -- Manager One
