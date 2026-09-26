-- Formula/Rule Configuration (client diagram: Web Portal control-center item)
-- Lets Org Admin tune the contractor risk-scoring weights instead of them being
-- fixed constants in Python. NULL means "use the built-in defaults".
ALTER TABLE organisation ADD COLUMN formula_config JSON NULL AFTER branding;
