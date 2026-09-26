"""
Run all SQL migrations in order against a MySQL database.

Usage:
    python run_migrations.py           apply everything not yet recorded
    python run_migrations.py --status  show ledger vs disk, change nothing

Configure DB credentials via environment variables or edit DB_CONFIG below.

Writing a migration — two constraints imposed by the naive splitter below:
  1. No `;` inside a comment. It splits the statement and silently truncates it.
  2. Do not end the file on a comment block. The trailing fragment is non-empty,
     reaches MySQL as an empty query, and errors. End on a real statement.
"""

import os
import re
import sys
import pymysql
from pathlib import Path

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", 3306)),
    "user":     os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "hse_db"),
}

MIGRATIONS_DIR = Path(__file__).parent

# MySQL errors that mean "this change is already in place". A migration being
# re-run over an already-migrated schema is the normal case when the ledger has
# drifted, so these are logged and skipped rather than raised.
#   1050 table already exists          1060 duplicate column
#   1061 duplicate key/index           1826 duplicate foreign key constraint name
#   1091 can't DROP, does not exist    1022 duplicate key on write
ALREADY_APPLIED_ERRNOS = (1050, 1060, 1061, 1826, 1091, 1022)


def _statements(sql: str):
    """Split a migration into executable statements.

    Walks the file character by character rather than calling sql.split(";"),
    because a naive split has broken migrations here in three ways:

      · a `;` inside a `--` comment truncated the statement that followed
      · a trailing comment block became an empty query and errored
      · a `;` inside a quoted string would have split mid-literal

    Comments are removed and statement boundaries are only recognised outside
    string literals and backtick-quoted identifiers. Everything else is passed
    through verbatim.
    """
    out, buf = [], []
    i, n = 0, len(sql)
    quote = None          # active ' " or ` — None when not inside one

    while i < n:
        ch = sql[i]

        if quote:
            buf.append(ch)
            if ch == "\\" and quote in ("'", '"') and i + 1 < n:
                buf.append(sql[i + 1])       # escaped char, cannot close string
                i += 2
                continue
            if ch == quote:
                # '' inside a string is an escaped quote, not a terminator.
                if quote in ("'", '"') and i + 1 < n and sql[i + 1] == quote:
                    buf.append(sql[i + 1])
                    i += 2
                    continue
                quote = None
            i += 1
            continue

        if ch in ("'", '"', "`"):
            quote = ch
            buf.append(ch)
            i += 1
        elif sql.startswith("--", i) or ch == "#":
            while i < n and sql[i] != "\n":
                i += 1
        elif sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
        elif ch == ";":
            out.append("".join(buf))
            buf = []
            i += 1
        else:
            buf.append(ch)
            i += 1

    out.append("".join(buf))
    for stmt in out:
        stmt = stmt.strip()
        if stmt:
            yield stmt


def _ledger_and_files(cursor):
    cursor.execute("SELECT filename FROM _migrations")
    applied = {row[0] for row in cursor.fetchall()}
    files = sorted(
        f for f in MIGRATIONS_DIR.glob("[0-9]*.sql") if "_ROLLBACK" not in f.name
    )
    return applied, files


def _check_no_new_duplicate_numbers(applied: set, files: list) -> None:
    """Two files sharing a numeric prefix (040/042/077 historically) run in
    whatever order `sorted()` happens to put their names in — not the order
    either was written to depend on. History already has a few of these
    (grandfathered below, since renumbering an applied filename would break
    the ledger's exact-filename match on every environment that already ran
    it) — but a *new* migration must never be added to a number that
    collides with another file still pending, or the next fresh bootstrap
    inherits the same luck-of-the-alphabet ordering risk.
    """
    by_prefix: dict[str, list] = {}
    for f in files:
        prefix = f.name.split("_", 1)[0]
        by_prefix.setdefault(prefix, []).append(f)

    for prefix, group in by_prefix.items():
        if len(group) < 2:
            continue
        if all(f.name in applied for f in group):
            continue  # historical collision, already resolved on disk — leave it
        names = ", ".join(f.name for f in group)
        raise SystemExit(
            f"Migration number {prefix} is used by more than one pending file: {names}. "
            "Renumber the new one before running — sorted() ordering between "
            "same-number files is not a dependency order."
        )


def show_status():
    """Print ledger vs disk without changing anything."""
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema = DATABASE() AND table_name = '_migrations'"
    )
    if not cursor.fetchone()[0]:
        print("  _migrations table does not exist yet — nothing has been recorded.")
        conn.close()
        return

    applied, files = _ledger_and_files(cursor)
    names = {f.name for f in files}
    pending = [f.name for f in files if f.name not in applied]
    orphans = sorted(a for a in applied if a not in names)

    print(f"  ledger: {len(applied)} recorded    disk: {len(files)} files")
    print(f"  pending ({len(pending)}): {pending or 'none'}")
    print(f"  recorded but no file ({len(orphans)}): {orphans or 'none'}")
    cursor.close()
    conn.close()


def run_migrations():
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()

    # Track applied migrations in a simple table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            filename    VARCHAR(255) UNIQUE NOT NULL,
            applied_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
    """)
    conn.commit()

    applied, sql_files = _ledger_and_files(cursor)
    _check_no_new_duplicate_numbers(applied, sql_files)
    ran = 0

    for sql_file in sql_files:
        if sql_file.name in applied:
            print(f"  skip  {sql_file.name}")
            continue

        print(f"  apply {sql_file.name} ...", end=" ", flush=True)
        sql = sql_file.read_text(encoding="utf-8")

        skipped = []
        try:
            for statement in _statements(sql):
                try:
                    cursor.execute(statement)
                except pymysql.err.OperationalError as e:
                    errno = e.args[0] if e.args else None
                    if errno in ALREADY_APPLIED_ERRNOS:
                        skipped.append(f"[{errno}] {e.args[1]}")
                    else:
                        raise
                except pymysql.err.IntegrityError as e:
                    errno = e.args[0] if e.args else None
                    if errno in ALREADY_APPLIED_ERRNOS:
                        skipped.append(f"[{errno}] {e.args[1]}")
                    else:
                        raise
        except Exception as e:
            # Leave the migration unrecorded so the next run retries it, and
            # name the file — a bare traceback does not say which one failed.
            conn.rollback()
            print("FAILED")
            print(f"\n  {sql_file.name} failed and was NOT recorded:\n    {e}")
            print(
                "\n  If this migration is in fact already applied, verify its objects\n"
                "  exist and then record it:\n"
                f"    INSERT INTO _migrations (filename) VALUES ('{sql_file.name}');"
            )
            cursor.close()
            conn.close()
            raise SystemExit(1)

        cursor.execute(
            "INSERT INTO _migrations (filename) VALUES (%s)", (sql_file.name,)
        )
        conn.commit()
        ran += 1
        print("done" if not skipped else f"done ({len(skipped)} already in place)")
        for s in skipped:
            print(f"          already applied: {s}")

    cursor.close()
    conn.close()
    print(f"\nAll migrations applied ({ran} newly run, {len(applied)} already recorded).")


if __name__ == "__main__":
    if "--status" in sys.argv:
        show_status()
    else:
        run_migrations()
