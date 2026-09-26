"""
Text-to-SQL agent — Claude writes the query, the backend decides whether to run it.

The flow is a two-turn Anthropic tool-use loop:

    question ──▶ Claude (schema + run_sql_query tool)
                   └─▶ tool_use { sql: "SELECT ..." }
                          ├─ validate()   ← the backend's judgement lives here
                          ├─ execute()    ← read-only, bounded, org-scoped
                          └─▶ tool_result rows
                                 └─▶ Claude phrases the final answer

The executor itself is deliberately dumb: it runs what validate() already
cleared and nothing else. Every safety property is enforced *before* the SQL
reaches the database, plus a second time by the database itself via a
SELECT-only grant (see docs/sql_agent_readonly_user.sql).

Guardrails, in the order an attacker would meet them:

  1. Schema whitelist   — Claude only ever sees ALLOWED_TABLES, never the full
                          95-table schema, so it cannot reference what it
                          cannot name.
  2. Statement shape    — single statement, SELECT/WITH only, comments stripped,
                          no stacked queries after a semicolon.
  3. Table whitelist    — every FROM/JOIN target is re-checked server-side, so a
                          hallucinated or injected table name is rejected even
                          though it was never in the prompt.
  4. Column denylist    — `SELECT *` is banned and sensitive columns
                          (password_hash, signatures, evidence blobs) cannot be
                          named.
  5. Tenant isolation   — the org id is NEVER taken from the model. Claude must
                          write the bind parameter `:org_id`; the value comes
                          from the caller's JWT at execution time.
  6. Row limit          — LIMIT is forced to at most MAX_ROWS.
  7. Timeout            — MySQL MAX_EXECUTION_TIME kills anything slower than
                          STATEMENT_TIMEOUT_MS.
  8. Read-only session  — the query runs inside a transaction that is always
                          rolled back, ideally as a SELECT-only DB user.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

import httpx
import sqlalchemy as sa
import sqlglot
from sqlglot import exp
from sqlalchemy.engine import Engine

from app.config.settings import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── Limits ────────────────────────────────────────────────────────────────────
MAX_ROWS = 100
STATEMENT_TIMEOUT_MS = 8_000
HTTP_TIMEOUT = 60.0
MAX_TOOL_ROUNDS = 4          # SQL → retry on error → retry again → forced answer
ANSWER_MAX_TOKENS = 700


class SqlAgentError(Exception):
    """Raised when the generated SQL is rejected or cannot be run."""


# ── 1. Schema whitelist ───────────────────────────────────────────────────────
# Only these tables and columns are ever described to the model. Curated rather
# than dumped: `incidents` alone has 78 columns, most of them signature blobs and
# workflow timestamps that cost tokens and answer no real question. Keeping this
# list tight is what holds the prompt near ~3.3k tokens instead of ~10.5k.
ALLOWED_TABLES: dict[str, list[str]] = {
    "incidents": [
        "id", "organisation_id", "report_date", "incident_date_time", "location_station_id",
        "incident_type", "severity", "severity_label", "number_persons_involved", "description",
        "immediate_cause", "root_cause", "root_cause_category", "investigation_status",
        "workflow_status", "days_away", "is_hipo", "dangerous_occurrence", "statutory_reportable",
        "reported_by", "reported_at", "closed_at", "created_at",
    ],
    "near_misses": [
        "id", "organisation_id", "report_date", "event_date_time", "location_station_id",
        "description", "potential_consequence", "underlying_cause", "root_cause", "severity",
        "assessed_label", "workflow_status", "is_hipo", "reported_by", "reported_at",
        "closed_at", "created_at",
    ],
    "unsafe_acts": [
        "id", "organisation_id", "report_date", "observed_date_time", "location_station_id",
        "act_type", "severity", "description", "rule_violated", "workflow_status",
        "reported_by", "reported_at", "closed_at", "created_at",
    ],
    "hazards": [
        "id", "organisation_id", "category_id", "hazard_name", "severity", "probability",
        "register_status", "description", "location_station_id", "logged_by", "logged_at",
        "reviewed_at", "created_at",
    ],
    "capa_actions": [
        "id", "organisation_id", "incident_id", "action_type", "description",
        "root_cause_addressed", "responsible_person_id", "due_date", "status",
        "effectiveness_rating", "priority_band", "capa_type_label", "created_at",
    ],
    "permits_to_work": [
        "id", "organisation_id", "permit_type_id", "date_issued", "location_station_id",
        "work_description", "duration_requested_hours", "validity_start", "validity_end",
        "number_of_workers", "status", "workflow_status", "deviation_reported",
        "incident_occurred", "is_high_energy", "zone", "contractor_company_id", "created_at",
    ],
    "audits": [
        "id", "organisation_id", "title", "checklist_type", "site_id", "site_name",
        "department", "auditor_id", "scheduled_date", "due_date", "status", "priority",
        "progress", "compliance_score", "submitted_at", "created_at",
    ],
    "safety_walks": [
        "id", "organisation_id", "inspection_date_time", "location_station_id", "inspector_id",
        "inspection_type", "issues_found", "critical_issues", "housekeeping_rating",
        "compliance_rating", "follow_up_required", "created_at",
    ],
    "training_records": [
        "id", "organisation_id", "employee_id", "training_program_id", "course_name",
        "completed_at", "expires_at", "score", "result", "created_at",
    ],
    "training_programs": ["id", "organisation_id", "created_at"],
    "sites": [
        "id", "organisation_id", "site_name", "city", "postcode", "region", "type",
        "operational_status", "number_of_working_stations", "capacity",
        "hazard_classification", "created_at",
    ],
    "working_stations": [
        "id", "organisation_id", "station_name", "site_id", "department",
        "zone_classification", "staffing_requirement", "created_at",
    ],
    "departments": [
        "id", "organisation_id", "site_id", "department_name", "manager_id",
        "number_of_teams", "created_at",
    ],
    "employees": [
        "id", "organisation_id", "full_name", "employment_type", "employment_start_date",
        "role_id", "department_id", "shift_pattern", "manager_id", "active_status", "created_at",
    ],
    "users": [
        "id", "organisation_id", "username", "full_name", "email", "app_role_id",
        "employee_id", "is_active", "last_login", "created_at",
    ],
    "shift_schedule": [
        "id", "organisation_id", "employee_id", "shift_date", "shift_type", "shift_start",
        "shift_end", "actual_hours_worked", "station_id", "supervisor_id",
    ],
    "assigned_tasks": ["id", "organisation_id", "created_at"],
    "contractor_companies": ["id", "organisation_id", "created_at"],
    "rams_scores": ["id", "organisation_id", "created_at"],
    "risk_reports": ["id", "organisation_id", "created_at"],
    "competence_matrix": ["id", "organisation_id", "created_at"],
    "emergency_drills": ["id", "organisation_id", "created_at"],
}

# Every whitelisted table carries organisation_id, so every one of them must be
# filtered by it. The `organisation` table itself is deliberately not exposed.
ORG_SCOPED_TABLES = set(ALLOWED_TABLES)

# 4. Column denylist — never selectable even if a table is otherwise allowed.
DENIED_COLUMNS = {
    "password_hash", "manager_signature", "supervisor_signature", "evidence_json",
    "witnesses_json", "evidence_photo", "photo_base64", "compliance_config",
    "branding", "formula_config", "severity_trace", "assessment_trace",
    "certificate_ref", "override_history",
}

# 2. Anything that could mutate, exfiltrate, stall, or probe the server.
FORBIDDEN_TOKENS = {
    "insert", "update", "delete", "drop", "alter", "create", "truncate", "rename",
    "grant", "revoke", "replace", "merge", "call", "execute", "exec", "handler",
    "load_file", "outfile", "dumpfile", "infile", "sleep", "benchmark",
    "information_schema", "performance_schema", "mysql", "sys", "into",
    "set", "lock", "unlock", "prepare", "deallocate", "do", "use",
    "get_lock", "master_pos_wait", "user", "current_user", "session_user",
    "version", "database", "schema", "connection_id", "load",
}

_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.S)
_COMMENT_LINE = re.compile(r"(--|#)[^\n]*")
_STRING_LITERAL = re.compile(r"'(?:[^'\\]|\\.|'')*'|\"(?:[^\"\\]|\\.|\"\")*\"")
_TABLE_REF = re.compile(r"\b(?:from|join)\s+`?([a-zA-Z_][a-zA-Z0-9_]*)`?", re.I)
_IDENTIFIER = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")
_LIMIT_CLAUSE = re.compile(r"\blimit\s+(\d+)\s*(?:,\s*(\d+)\s*)?$", re.I)


# ── Schema prompt ─────────────────────────────────────────────────────────────
_schema_cache: Optional[str] = None


def build_schema_prompt() -> str:
    """Render the whitelist as compact DDL for the system prompt.

    Types come from information_schema so the description can't drift from the
    real table, but only whitelisted columns are ever emitted. Cached because it
    is a byte-stable prefix — that is what makes prompt caching work.
    """
    global _schema_cache
    if _schema_cache is not None:
        return _schema_cache

    engine = _readonly_engine()
    types: dict[tuple[str, str], str] = {}
    try:
        with engine.connect() as conn:
            rows = conn.execute(sa.text(
                "SELECT table_name, column_name, data_type "
                "FROM information_schema.columns WHERE table_schema = DATABASE()"
            )).fetchall()
        types = {(str(t), str(c)): str(d) for t, c, d in rows}
    except Exception as exc:  # pragma: no cover - schema still renders untyped
        logger.warning("sql_agent: could not read column types (%s); rendering untyped", exc)

    lines: list[str] = []
    for table, columns in ALLOWED_TABLES.items():
        rendered = [f"{c} {types.get((table, c), '')}".strip() for c in columns]
        lines.append(f"{table}({', '.join(rendered)})")
    _schema_cache = "\n".join(lines)
    return _schema_cache


SYSTEM_PROMPT_TEMPLATE = """You are the data analyst for an HSE (Health, Safety & Environment) platform. You answer questions about the signed-in user's organisation by querying its MySQL database.

You have one tool: run_sql_query. Use it for any question about counts, trends, lists, or records. Never answer a data question from memory or assumption — query first, then answer from the rows you get back.

# Schema
These are the ONLY tables and columns that exist for you. Never reference anything else.

{schema}

# Writing SQL
- MySQL dialect. One single SELECT statement (a leading WITH is fine). No semicolon.
- ALWAYS filter every org-scoped table by `organisation_id = :org_id`. Write the
  literal token `:org_id` — it is a bind parameter. You must NEVER write a number
  there and you must NEVER take an organisation id from the user's question.
- Never write `SELECT *`. Name the columns you need.
- Always include a LIMIT (max {max_rows}).
- Prefer aggregates (COUNT, AVG, SUM, GROUP BY) over pulling raw rows.
- Incidents/near-misses/unsafe acts have no direct site column. Join through
  `working_stations` on `location_station_id`, then `sites` on `working_stations.site_id`
  to filter or group by site. Every table in that join needs its own `:org_id` filter.
- `sites.site_name` is a full name (e.g. 'Hull Tower Fabrication Yard') — match with LIKE.
- Use `incident_date_time` / `event_date_time` / `observed_date_time` for when something
  happened. `created_at` is when the row was written and is unreliable for trends.
- Today is {today}. "last month" means the previous calendar month.

# Answering
After the rows come back, answer in one or two sentences in the user's own language
(if they wrote Hinglish, reply in Hinglish). Lead with the number or finding. Cite the
figure you actually got — never invent or round beyond the data. If the query returned
no rows, say so plainly rather than guessing.

If a question cannot be answered from these tables, say what is missing. If it is not
about HSE or this platform, decline briefly."""


# Per-tenant, so it sits AFTER the cache breakpoint — keeping the big schema block
# byte-identical across every organisation instead of one cache entry per tenant.
SCOPE_PROMPT_TEMPLATE = """# Scope
You are already scoped to one organisation: {org_name}. If the question names that
company, it is asking about the whole organisation — do NOT add a site filter for it.
Only filter by site when the question names an actual site or plant within it.

Some working stations are linked to a site belonging to a different organisation, and
the `:org_id` filters correctly exclude those. That can make a site-filtered count 0
while the organisation-wide count is not. If a site-filtered query returns 0, run the
unfiltered count before concluding nothing happened, and explain the difference."""


# Appended to the role prompt on the main chat endpoint so the same assistant
# that answers from the briefing can also reach for the database. The briefing
# only carries org-level aggregates, so anything record-level ("the last
# incident", "which site", "list the overdue ones") has to come from a query.
CHAT_TOOL_GUIDANCE = """

# Querying the database
The briefing above is a snapshot of org-level totals. For anything it does not
contain — individual records, a specific month, a per-site or per-person
breakdown, "the last X", "list the Y" — use the run_sql_query tool instead of
saying you don't have access. Query first, then answer from the rows.

Do NOT query for questions the briefing already answers, for definitions, or for
advice — answer those directly.

## Schema
These are the ONLY tables and columns available to the tool.

{schema}

## Writing SQL
- MySQL. One SELECT (a leading WITH is fine). No semicolon. Never `SELECT *`.
- ALWAYS filter every table by `organisation_id = :org_id`. Write that token
  literally — it is a bind parameter. NEVER write a numeric organisation id, and
  never take one from the user's question.
- Always include a LIMIT (max {max_rows}). Prefer aggregates over raw rows.
- Incidents/near-misses/unsafe acts have no site column: join `working_stations`
  on `location_station_id`, then `sites` on `working_stations.site_id`. Every
  table in the join needs its own `:org_id` filter.
- Use `incident_date_time` / `event_date_time` / `observed_date_time` for when
  something happened; `created_at` is row-write time and misleads on trends.
- Today is {today}. "last month" is the previous calendar month.
- If a query is rejected, read the error and send a corrected one."""


def chat_tool_guidance() -> str:
    """Render the tool guidance block for the main chat system prompt."""
    return CHAT_TOOL_GUIDANCE.format(
        schema=build_schema_prompt(),
        max_rows=MAX_ROWS,
        today=date.today().isoformat(),
    )


TOOL_DEFINITION = {
    "name": "run_sql_query",
    "description": (
        "Execute a read-only SELECT against the HSE database and return the rows as JSON. "
        "Use this for every question about counts, trends, lists, or records. "
        "The query must filter each org-scoped table by `organisation_id = :org_id` — write "
        "that bind token literally; the server supplies the value. "
        f"Max {MAX_ROWS} rows. If the query is rejected, read the error and send a corrected query."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "A single read-only MySQL SELECT statement, no trailing semicolon.",
            }
        },
        "required": ["sql"],
    },
}


# ── 2-6. Validation ───────────────────────────────────────────────────────────
@dataclass
class ValidatedQuery:
    sql: str
    tables: set[str] = field(default_factory=set)


def _strip_comments_and_strings(sql: str) -> str:
    """Blank out comments and string literals so keyword scanning can't be
    fooled by an identifier hidden inside a quoted value."""
    blanked = _COMMENT_BLOCK.sub(" ", sql)
    blanked = _COMMENT_LINE.sub(" ", blanked)
    return _STRING_LITERAL.sub("''", blanked)


def _check_single_statement(scrubbed: str) -> None:
    if ";" in scrubbed.rstrip().rstrip(";"):
        raise SqlAgentError("Stacked statements are not allowed — send exactly one SELECT.")
    if not scrubbed.strip():
        raise SqlAgentError("Empty query.")


def _check_select_only(scrubbed: str) -> None:
    head = scrubbed.strip().lower()
    if not (head.startswith("select") or head.startswith("with")):
        raise SqlAgentError("Only SELECT queries are allowed (a leading WITH is fine).")

    words = {w.lower() for w in _IDENTIFIER.findall(scrubbed)}
    hits = sorted(words & FORBIDDEN_TOKENS)
    if hits:
        raise SqlAgentError(
            f"Query rejected: forbidden keyword(s) {', '.join(hits)}. "
            "Only plain read-only SELECT syntax over the listed tables is permitted."
        )


def _check_tables(scrubbed: str) -> set[str]:
    refs = {m.group(1).lower() for m in _TABLE_REF.finditer(scrubbed)}
    # A CTE name is defined in-query, so allow anything bound by WITH ... AS.
    ctes = {m.lower() for m in re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s+as\s*\(", scrubbed, re.I)}
    unknown = sorted(t for t in refs - ctes if t not in ALLOWED_TABLES)
    if unknown:
        raise SqlAgentError(
            f"Unknown or not-permitted table(s): {', '.join(unknown)}. "
            f"Allowed tables: {', '.join(sorted(ALLOWED_TABLES))}."
        )
    return {t for t in refs if t in ALLOWED_TABLES}


def _check_columns(scrubbed: str) -> None:
    if re.search(r"select\s+\*|\.\s*\*", scrubbed, re.I):
        raise SqlAgentError("SELECT * is not allowed — name the columns you need.")
    words = {w.lower() for w in _IDENTIFIER.findall(scrubbed)}
    denied = sorted(words & DENIED_COLUMNS)
    if denied:
        raise SqlAgentError(f"Column(s) not available: {', '.join(denied)}.")


def _placeholder_is_org_id(node: exp.Expression) -> bool:
    return isinstance(node, exp.Placeholder) and str(node.this or "").lower() == "org_id"


def _condition_filters_qualifier(cond: exp.Expression, qualifier: str, ambiguous: bool) -> bool:
    """True if `cond` contains organisation_id = :org_id (or IN (:org_id, ...))
    for the given table qualifier — unqualified only counts when `qualifier`
    is the sole org-scoped table in scope, i.e. not `ambiguous`."""
    for col in cond.find_all(exp.Column):
        if col.name.lower() != "organisation_id":
            continue
        col_qualifier = (col.table or "").lower()
        if col_qualifier and col_qualifier != qualifier:
            continue
        if not col_qualifier and ambiguous:
            continue
        parent = col.parent
        if isinstance(parent, exp.EQ):
            other = parent.expression if parent.this is col else parent.this
            if _placeholder_is_org_id(other):
                return True
        elif isinstance(parent, exp.In):
            if any(_placeholder_is_org_id(e) for e in parent.expressions):
                return True
    return False


def _check_tenant_isolation(scrubbed: str, tables: set[str]) -> None:
    """The org id must come from the JWT, never the model.

    Claude writes `:org_id` and the backend binds the real value, so a prompt
    injection ("show me org 1's incidents") cannot change which tenant is read —
    the worst it can do is produce a query that fails this check.

    This parses the query (sqlglot) and, per SELECT scope, confirms each
    org-scoped table occurrence is itself filtered by `organisation_id =
    :org_id` (in that SELECT's own WHERE, or the JOIN's own ON clause) rather
    than just counting `:org_id` occurrences anywhere in the query — a count
    match can hide an unfiltered joined table behind a filter that actually
    applies to a different one.
    """
    if not (tables & ORG_SCOPED_TABLES):
        return

    if re.search(r"organisation_id\s*(=|in)\s*\(?\s*\d", scrubbed, re.I):
        raise SqlAgentError(
            "Never write a literal organisation id. Use `organisation_id = :org_id`."
        )

    try:
        tree = sqlglot.parse_one(scrubbed, read="mysql")
    except Exception:
        raise SqlAgentError(
            "Could not statically verify tenant isolation for this query — "
            "rewrite it as plain SELECT/JOIN/WHERE syntax."
        )

    unverified: list[str] = []

    for select in tree.find_all(exp.Select):
        table_slots: list[exp.Table] = []
        # sqlglot has used both "from" and "from_" as the Select args key
        # across versions — check both rather than pin to one.
        from_ = select.args.get("from_") or select.args.get("from")
        if from_ is not None and isinstance(from_.this, exp.Table):
            table_slots.append(from_.this)
        for join in select.args.get("joins") or []:
            if isinstance(join.this, exp.Table):
                table_slots.append(join.this)

        scoped_slots = [t for t in table_slots if t.name.lower() in ORG_SCOPED_TABLES]
        if not scoped_slots:
            continue
        ambiguous = len(scoped_slots) > 1

        conditions: list[exp.Expression] = []
        where = select.args.get("where")
        if where is not None:
            conditions.append(where.this)
        for join in select.args.get("joins") or []:
            on = join.args.get("on")
            if on is not None:
                conditions.append(on)

        for table_slot in scoped_slots:
            qualifier = (table_slot.alias_or_name or table_slot.name).lower()
            if not any(_condition_filters_qualifier(cond, qualifier, ambiguous) for cond in conditions):
                unverified.append(f"{table_slot.name}" + (f" ({qualifier})" if qualifier != table_slot.name.lower() else ""))

    if unverified:
        raise SqlAgentError(
            "Missing tenant filter for: " + ", ".join(unverified) + ". Every "
            "org-scoped table reference needs its own `organisation_id = "
            ":org_id` in the WHERE clause or that table's JOIN ON clause."
        )


def _enforce_limit(sql: str, scrubbed: str) -> str:
    """Force a bounded result set. An existing LIMIT is clamped, not trusted."""
    match = _LIMIT_CLAUSE.search(scrubbed.strip())
    if not match:
        return f"{sql.rstrip().rstrip(';')} LIMIT {MAX_ROWS}"
    requested = int(match.group(2) or match.group(1))
    if requested <= MAX_ROWS:
        return sql.rstrip().rstrip(";")
    clamped = _LIMIT_CLAUSE.sub(f"LIMIT {MAX_ROWS}", sql.rstrip().rstrip(";").strip())
    logger.info("sql_agent: clamped LIMIT %s -> %s", requested, MAX_ROWS)
    return clamped


def validate_sql(sql: str) -> ValidatedQuery:
    """Run every static guardrail. Raises SqlAgentError with a message that is
    safe (and useful) to hand back to the model as a tool_result error."""
    if not isinstance(sql, str) or not sql.strip():
        raise SqlAgentError("No SQL provided.")

    scrubbed = _strip_comments_and_strings(sql)
    _check_single_statement(scrubbed)
    _check_select_only(scrubbed)
    tables = _check_tables(scrubbed)
    _check_columns(scrubbed)
    _check_tenant_isolation(scrubbed, tables)
    return ValidatedQuery(sql=_enforce_limit(sql, scrubbed), tables=tables)


# ── 7-8. Execution ────────────────────────────────────────────────────────────
_engine: Optional[Engine] = None


def _readonly_engine() -> Engine:
    """Engine for LLM-generated SQL.

    Uses `sql_agent_database_url` when configured — that should point at a
    SELECT-only MySQL user (docs/sql_agent_readonly_user.sql), which is the one
    guardrail that still holds if every check above is bypassed. Falls back to
    the app connection so the feature works before that user is provisioned.
    """
    global _engine
    if _engine is not None:
        return _engine

    settings = get_settings()
    url = getattr(settings, "sql_agent_database_url", "") or settings.effective_database_url
    if url == settings.effective_database_url:
        logger.warning(
            "sql_agent: SQL_AGENT_DATABASE_URL not set — LLM queries run as the app DB user. "
            "Provision the read-only user (docs/sql_agent_readonly_user.sql) before production."
        )
    _engine = sa.create_engine(url, pool_pre_ping=True, pool_size=3, max_overflow=2, echo=False)
    return _engine


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return "<binary>"
    return value


def execute_sql(validated: ValidatedQuery, org_id: int) -> list[dict[str, Any]]:
    """Run pre-validated SQL. Dumb on purpose — every decision was made above.

    `org_id` comes from the caller's JWT and is bound here; it is the only way a
    tenant value ever enters the query.
    """
    engine = _readonly_engine()
    with engine.connect() as conn:
        try:
            conn.execute(sa.text(f"SET SESSION MAX_EXECUTION_TIME={STATEMENT_TIMEOUT_MS}"))
        except Exception:  # non-MySQL or insufficient grant — timeout enforced by driver
            logger.debug("sql_agent: MAX_EXECUTION_TIME unsupported on this connection")
        try:
            result = conn.execute(sa.text(validated.sql), {"org_id": org_id})
            rows = [
                {k: _jsonable(v) for k, v in dict(r._mapping).items()}
                for r in result.fetchmany(MAX_ROWS)
            ]
        finally:
            # Never let an LLM-driven statement leave a transaction open.
            conn.rollback()
    return rows


def run_tool(sql: str, org_id: int) -> tuple[str, bool]:
    """validate + execute, returning (tool_result_content, is_error).

    Errors are returned rather than raised so Claude can read the reason and
    correct its own query on the next round.
    """
    try:
        validated = validate_sql(sql)
    except SqlAgentError as exc:
        logger.warning("sql_agent: rejected query for org %s: %s | sql=%s", org_id, exc, sql)
        return f"Query rejected: {exc}", True

    started = time.perf_counter()
    try:
        rows = execute_sql(validated, org_id)
    except Exception as exc:
        msg = str(getattr(exc, "orig", exc))[:300]
        logger.warning("sql_agent: execution failed for org %s: %s", org_id, msg)
        return f"Query failed: {msg}", True

    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "sql_agent: org=%s rows=%s %.0fms tables=%s",
        org_id, len(rows), elapsed_ms, ",".join(sorted(validated.tables)),
    )
    if not rows:
        return "No rows matched.", False
    return json.dumps(rows, default=str), False


# ── Anthropic tool-use loop ───────────────────────────────────────────────────
def _post_messages(body: dict) -> dict:
    """Call the Messages API — Azure AI Foundry deployment or standard Anthropic."""
    settings = get_settings()
    api_key = settings.anthropic_api_key
    if not api_key:
        raise SqlAgentError("ANTHROPIC_API_KEY is not configured.")

    base_url = settings.anthropic_base_url
    if base_url:
        endpoint = base_url.rstrip("/") + "/v1/messages"
        common = {"anthropic-version": "2023-06-01", "content-type": "application/json"}
        last: Optional[httpx.Response] = None
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            for headers in (
                {"Authorization": f"Bearer {api_key}", **common},
                {"api-key": api_key, **common},
            ):
                last = client.post(endpoint, json=body, headers=headers)
                if last.status_code != 401:
                    break
        last.raise_for_status()
        return last.json()

    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    return client.messages.create(**body).model_dump()


def _org_name(org_id: int) -> str:
    """Look up the caller's organisation name so the model can tell "my company"
    from "a site inside my company". Read via the same read-only connection."""
    try:
        with _readonly_engine().connect() as conn:
            row = conn.execute(
                sa.text("SELECT organisation_name FROM organisation WHERE id = :id"),
                {"id": org_id},
            ).first()
        return str(row[0]) if row and row[0] else f"organisation #{org_id}"
    except Exception as exc:
        logger.warning("sql_agent: org name lookup failed for %s: %s", org_id, exc)
        return f"organisation #{org_id}"


def answer_question(question: str, org_id: int, history: Optional[list[dict]] = None) -> dict:
    """Full flow: question → SQL → validate → execute → phrased answer.

    Returns {answer, sql, rows, rounds, model} so the UI can show the figure and,
    if it wants, the query behind it.
    """
    settings = get_settings()
    model = settings.anthropic_model

    system = [
        {
            "type": "text",
            "text": SYSTEM_PROMPT_TEMPLATE.format(
                schema=build_schema_prompt(),
                max_rows=MAX_ROWS,
                today=date.today().isoformat(),
            ),
            # Byte-stable across every tenant — cache reads bill at ~0.1x and cut
            # time-to-first-token. The volatile per-org block goes after this.
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": SCOPE_PROMPT_TEMPLATE.format(org_name=_org_name(org_id)),
        },
    ]

    messages: list[dict] = list(history or [])
    messages.append({"role": "user", "content": question})

    executed_sql: list[str] = []
    last_rows: Optional[str] = None

    for round_no in range(MAX_TOOL_ROUNDS):
        # On the final round, withhold the tool so the model has to answer from
        # the rows it already has. Without this, a question it keeps re-querying
        # ends the loop with no text at all and the user gets a dead-end reply.
        last_round = round_no == MAX_TOOL_ROUNDS - 1
        if last_round:
            # The preceding message is bare tool_result blocks. Without something
            # addressed to it, the model just ends the turn with empty content.
            messages.append({
                "role": "user",
                "content": (
                    "Stop querying and answer now, using only the query results above. "
                    "If they are incomplete or empty, say what you did find and what "
                    "could not be determined."
                ),
            })
        body = {
            "model": model,
            "max_tokens": ANSWER_MAX_TOKENS,
            "system": system,
            "messages": messages,
        }
        if not last_round:
            body["tools"] = [TOOL_DEFINITION]
        data = _post_messages(body)

        usage = data.get("usage") or {}
        logger.info(
            "sql_agent usage: in=%s cache_read=%s out=%s",
            usage.get("input_tokens"), usage.get("cache_read_input_tokens"),
            usage.get("output_tokens"),
        )

        content = data.get("content") or []
        if data.get("stop_reason") != "tool_use":
            text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            return {
                "answer": text.strip() or "I could not produce an answer.",
                "sql": executed_sql,
                "rows": last_rows,
                "model": data.get("model", model),
            }

        messages.append({"role": "assistant", "content": content})

        results = []
        for block in content:
            if block.get("type") != "tool_use" or block.get("name") != "run_sql_query":
                continue
            sql = (block.get("input") or {}).get("sql", "")
            body, is_error = run_tool(sql, org_id)
            if not is_error:
                executed_sql.append(sql)
                last_rows = body
            results.append({
                "type": "tool_result",
                "tool_use_id": block.get("id"),
                "content": body,
                **({"is_error": True} if is_error else {}),
            })

        if not results:
            break
        messages.append({"role": "user", "content": results})

    return {
        "answer": "I couldn't get a valid query to run for that question. Try rephrasing it.",
        "sql": executed_sql,
        "rows": last_rows,
        "model": model,
    }
