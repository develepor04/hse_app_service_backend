"""One-off data repair: clear employee-reference columns on tenant-owned
records where the referenced employee belongs to a different organisation.

Same root cause as repair_capa_assignee_org_mismatch.py (that script already
handled capa_actions.responsible_person_id) — employee ids are a global,
cross-tenant primary key, so older seed data let these columns point at
another org's employee. Reads are already defended (app/utils/tenant.py
org_scoped_join), but the raw columns still carry the wrong reference.

Covers:
    incidents.reported_by
    near_misses.reported_by
    safety_walks.inspector_id
    permits_to_work.issued_by
    permits_to_work.approved_by

Non-destructive: every value touched is copied into
_employee_ref_mismatch_backup first (table, row id, column, old value, both
org ids), so any of it can be restored. Only the FK column is cleared (set to
NULL); the owning record itself is untouched.

Usage:
    python scripts/repair_employee_ref_org_mismatch.py            # dry run
    python scripts/repair_employee_ref_org_mismatch.py --apply    # apply
"""
import argparse
import os

import pymysql
from dotenv import load_dotenv

load_dotenv()

# (table, org_column, employee_fk_column)
TARGETS = [
    ("incidents", "organisation_id", "reported_by"),
    ("near_misses", "organisation_id", "reported_by"),
    ("safety_walks", "organisation_id", "inspector_id"),
    ("permits_to_work", "organisation_id", "issued_by"),
    ("permits_to_work", "organisation_id", "approved_by"),
]


def get_connection():
    return pymysql.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "hse_db"),
    )


def find_mismatches(cur, table, org_col, fk_col):
    cur.execute(
        f"""
        SELECT t.id, t.{org_col}, t.{fk_col}, e.organisation_id
        FROM {table} t
        JOIN employees e ON t.{fk_col} = e.id
        WHERE t.{org_col} IS NOT NULL AND e.organisation_id IS NOT NULL
          AND t.{org_col} != e.organisation_id
        """
    )
    return cur.fetchall()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually write changes. Without this flag, only reports what would change.")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    plan = []
    total = 0
    for table, org_col, fk_col in TARGETS:
        rows = find_mismatches(cur, table, org_col, fk_col)
        plan.append((table, org_col, fk_col, rows))
        total += len(rows)
        print(f"{table}.{fk_col}: {len(rows)} mismatched rows")

    if total == 0:
        print("\nNo mismatches found anywhere. Nothing to do.")
        return

    if not args.apply:
        print(f"\nDry run only — {total} rows total would be cleared. Re-run with --apply to back up and clear them.")
        return

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS _employee_ref_mismatch_backup (
            table_name VARCHAR(64) NOT NULL,
            row_id INT NOT NULL,
            column_name VARCHAR(64) NOT NULL,
            old_employee_id INT,
            record_organisation_id INT,
            employee_organisation_id INT,
            repaired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (table_name, row_id, column_name)
        )
        """
    )

    grand_total = 0
    for table, org_col, fk_col, rows in plan:
        if not rows:
            continue
        for row_id, rec_org, emp_id, emp_org in rows:
            cur.execute(
                """
                INSERT INTO _employee_ref_mismatch_backup
                    (table_name, row_id, column_name, old_employee_id, record_organisation_id, employee_organisation_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    old_employee_id = VALUES(old_employee_id),
                    record_organisation_id = VALUES(record_organisation_id),
                    employee_organisation_id = VALUES(employee_organisation_id)
                """,
                (table, row_id, fk_col, emp_id, rec_org, emp_org),
            )
        row_ids = [r[0] for r in rows]
        placeholders = ",".join(["%s"] * len(row_ids))
        cur.execute(
            f"UPDATE {table} SET {fk_col} = NULL WHERE id IN ({placeholders})",
            row_ids,
        )
        print(f"Cleared {table}.{fk_col} on {len(rows)} rows.")
        grand_total += len(rows)

    conn.commit()
    print(f"\nBacked up and cleared {grand_total} mismatched references.")
    print("Backup table: _employee_ref_mismatch_backup")


if __name__ == "__main__":
    main()
