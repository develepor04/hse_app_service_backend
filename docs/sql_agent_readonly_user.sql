-- Read-only MySQL user for the text-to-SQL agent (app/services/sql_agent.py).
--
-- Every LLM-generated query is validated in Python first, but validation is
-- code and code has bugs. This grant is the layer that does not depend on that
-- code being correct: even a query that slips past every check cannot write,
-- because the connection has no privilege to write.
--
-- Run once as root, then set in backend/.env:
--   SQL_AGENT_DATABASE_URL=mysql+pymysql://hse_sql_agent:CHANGE_ME@localhost:3306/hse_db
--
-- Pick a real password before running. Do not reuse the app user's password.

CREATE USER IF NOT EXISTS 'hse_sql_agent'@'localhost'
  IDENTIFIED BY 'CHANGE_ME';

-- Start from zero in case the user already existed with wider rights.
REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'hse_sql_agent'@'localhost';

-- SELECT only, and only on the application schema. No INSERT/UPDATE/DELETE,
-- no DROP/ALTER/CREATE, no FILE (blocks LOAD_FILE and SELECT ... INTO OUTFILE),
-- no PROCESS, no SUPER.
GRANT SELECT ON hse_db.* TO 'hse_sql_agent'@'localhost';

-- Cap the blast radius of a runaway or abusive query. MAX_QUERIES_PER_HOUR is a
-- coarse rate limit on top of the per-request timeout the agent already sets.
ALTER USER 'hse_sql_agent'@'localhost'
  WITH MAX_QUERIES_PER_HOUR 2000
       MAX_USER_CONNECTIONS 5;

FLUSH PRIVILEGES;

-- Verify — this should list exactly one GRANT SELECT line plus USAGE:
SHOW GRANTS FOR 'hse_sql_agent'@'localhost';

-- Sanity checks (run while connected AS hse_sql_agent — both must fail):
--   INSERT INTO incidents (description) VALUES ('x');   -- ERROR 1142
--   DROP TABLE incidents;                               -- ERROR 1142
