"""Guardrail tests for the text-to-SQL agent.

`validate_sql` is a security boundary: it is the only thing standing between
model-generated text and the database, and the whitelist it enforces is easy to
widen by accident. These tests pin that boundary.

Pure unit tests — no database, no API key, no network.

    cd backend && python3.11 -m pytest tests/test_sql_agent.py -q
"""
import pytest

from app.services.sql_agent import (
    ALLOWED_TABLES,
    DENIED_COLUMNS,
    MAX_ROWS,
    ORG_SCOPED_TABLES,
    SqlAgentError,
    validate_sql,
)


def blocked(sql: str) -> str:
    """Assert the query is rejected and hand back the reason."""
    with pytest.raises(SqlAgentError) as excinfo:
        validate_sql(sql)
    return str(excinfo.value)


# ── Legitimate queries must survive ───────────────────────────────────────────
SIMPLE_COUNT = "SELECT COUNT(*) AS c FROM incidents WHERE organisation_id = :org_id"

SITE_JOIN = (
    "SELECT COUNT(*) AS c FROM incidents i "
    "JOIN working_stations ws ON i.location_station_id = ws.id "
    "AND ws.organisation_id = :org_id "
    "JOIN sites s ON ws.site_id = s.id AND s.organisation_id = :org_id "
    "WHERE i.organisation_id = :org_id AND s.site_name LIKE '%Hull%'"
)

CTE = (
    "WITH m AS (SELECT severity, COUNT(*) c FROM incidents "
    "WHERE organisation_id = :org_id GROUP BY severity) SELECT severity, c FROM m"
)


@pytest.mark.parametrize("sql", [SIMPLE_COUNT, SITE_JOIN, CTE])
def test_valid_queries_pass(sql):
    assert validate_sql(sql).sql


def test_date_filtered_aggregate_passes():
    validate_sql(
        "SELECT COUNT(*) AS c FROM incidents WHERE organisation_id = :org_id "
        "AND incident_date_time >= '2026-07-01' AND incident_date_time < '2026-08-01'"
    )


def test_tables_are_reported():
    assert validate_sql(SITE_JOIN).tables == {"incidents", "working_stations", "sites"}


# ── 2. Statement shape ────────────────────────────────────────────────────────
def test_stacked_statement_blocked():
    assert "Stacked" in blocked(f"{SIMPLE_COUNT}; DROP TABLE incidents")


def test_trailing_semicolon_allowed():
    assert validate_sql(f"{SIMPLE_COUNT};").sql.count(";") == 0


@pytest.mark.parametrize("sql", [
    "UPDATE incidents SET severity='low' WHERE organisation_id = :org_id",
    "DELETE FROM incidents WHERE organisation_id = :org_id",
    "DROP TABLE incidents",
    "INSERT INTO incidents (description) VALUES ('x')",
])
def test_write_statements_blocked(sql):
    blocked(sql)


@pytest.mark.parametrize("sql", [
    f"{SIMPLE_COUNT} INTO OUTFILE '/tmp/x'",
    "SELECT SLEEP(30) FROM incidents WHERE organisation_id = :org_id",
    "SELECT BENCHMARK(1000000, MD5('x')) FROM incidents WHERE organisation_id = :org_id",
    "SELECT LOAD_FILE('/etc/passwd') FROM incidents WHERE organisation_id = :org_id",
])
def test_exfiltration_and_dos_blocked(sql):
    blocked(sql)


def test_empty_query_blocked():
    blocked("   ")


# ── 3. Table whitelist ────────────────────────────────────────────────────────
@pytest.mark.parametrize("sql", [
    "SELECT id FROM api_keys WHERE organisation_id = :org_id",
    "SELECT table_name FROM information_schema.tables",
    "SELECT host FROM mysql.user",
    f"{SIMPLE_COUNT} /*x*/ UNION SELECT id FROM api_keys",
])
def test_non_whitelisted_tables_blocked(sql):
    blocked(sql)


def test_every_whitelisted_table_is_org_scoped():
    """A table reachable without an org filter is a cross-tenant leak."""
    assert set(ALLOWED_TABLES) == ORG_SCOPED_TABLES


def test_organisation_table_is_not_exposed():
    assert "organisation" not in ALLOWED_TABLES


# ── 4. Column denylist ────────────────────────────────────────────────────────
def test_select_star_blocked():
    assert "SELECT *" in blocked("SELECT * FROM incidents WHERE organisation_id = :org_id")


def test_qualified_star_blocked():
    blocked("SELECT i.* FROM incidents i WHERE i.organisation_id = :org_id")


def test_password_hash_blocked():
    assert "password_hash" in blocked(
        "SELECT password_hash FROM users WHERE organisation_id = :org_id"
    )


def test_union_to_denied_column_blocked():
    blocked(f"{SIMPLE_COUNT} UNION SELECT password_hash FROM users")


def test_denied_columns_are_not_also_whitelisted():
    """A column can't be both offered to the model and denied to it."""
    offered = {c for cols in ALLOWED_TABLES.values() for c in cols}
    assert offered & DENIED_COLUMNS == set()


# ── 5. Tenant isolation — the one that matters most ───────────────────────────
def test_missing_tenant_filter_blocked():
    assert "tenant" in blocked("SELECT COUNT(*) AS c FROM incidents").lower()


def test_literal_org_id_blocked():
    blocked("SELECT COUNT(*) AS c FROM incidents WHERE organisation_id = 1")


def test_org_id_in_list_blocked():
    blocked("SELECT COUNT(*) AS c FROM incidents WHERE organisation_id IN (1,2)")


def test_bound_org_id_or_literal_blocked():
    """The classic widening attack: keep the bind, OR in another tenant."""
    assert "literal" in blocked(
        "SELECT COUNT(*) AS c FROM incidents "
        "WHERE organisation_id = :org_id OR organisation_id = 1"
    ).lower()


def test_join_with_one_unfiltered_table_blocked():
    """Two org-scoped tables, one filter — users would leak across tenants."""
    assert "org_id" in blocked(
        "SELECT COUNT(*) AS c FROM incidents i JOIN users u ON i.reported_by = u.id "
        "WHERE i.organisation_id = :org_id"
    )


def test_join_with_both_tables_filtered_passes():
    validate_sql(
        "SELECT COUNT(*) AS c FROM incidents i JOIN users u ON i.reported_by = u.id "
        "AND u.organisation_id = :org_id WHERE i.organisation_id = :org_id"
    )


# ── 6. Row limit ──────────────────────────────────────────────────────────────
def test_limit_is_added_when_absent():
    assert validate_sql(SIMPLE_COUNT).sql.rstrip().endswith(f"LIMIT {MAX_ROWS}")


def test_oversized_limit_is_clamped():
    sql = validate_sql(
        "SELECT id FROM incidents WHERE organisation_id = :org_id LIMIT 5000"
    ).sql
    assert "5000" not in sql and f"LIMIT {MAX_ROWS}" in sql


def test_small_limit_is_respected():
    assert validate_sql(
        "SELECT id FROM incidents WHERE organisation_id = :org_id LIMIT 20"
    ).sql.rstrip().endswith("LIMIT 20")
