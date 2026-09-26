"""One-off data repair: clear CapaAction.responsible_person_id where the
referenced employee belongs to a different organisation than the CAPA action.

Root cause (fixed separately in app code): employee ids are a global,
cross-tenant primary key, and older seed data / a since-patched assign
endpoint let a CAPA's responsible_person_id point at another org's employee.
Reads are already defended (app/utils/tenant.py org_scoped_join), but the
raw column still carries the wrong reference — this repairs that.

Non-destructive: every row touched is copied into
_capa_assignee_mismatch_backup first, so the original value can be restored.
Only responsible_person_id is cleared (set to NULL); the CAPA record itself
is untouched.

Usage:
    python scripts/repair_capa_assignee_org_mismatch.py            # dry run
    python scripts/repair_capa_assignee_org_mismatch.py --apply    # apply
"""
import argparse
import os
import sys

import pymysql
from dotenv import load_dotenv

load_dotenv()


def get_connection():
    return pymysql.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "hse_db"),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually write changes. Without this flag, only reports what would change.")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT c.id, c.organisation_id, c.responsible_person_id, e.organisation_id
        FROM capa_actions c
        JOIN employees e ON c.responsible_person_id = e.id
        WHERE c.organisation_id IS NOT NULL AND e.organisation_id IS NOT NULL
          AND c.organisation_id != e.organisation_id
        """
    )
    rows = cur.fetchall()

    if not rows:
        print("No mismatched capa_actions.responsible_person_id rows found. Nothing to do.")
        return

    print(f"Found {len(rows)} capa_actions rows whose responsible_person_id points at another org's employee:")
    for capa_id, capa_org, emp_id, emp_org in rows:
        print(f"  capa_actions.id={capa_id} (org {capa_org}) -> employees.id={emp_id} (org {emp_org})")

    if not args.apply:
        print("\nDry run only — re-run with --apply to back up and clear these references.")
        return

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS _capa_assignee_mismatch_backup (
            capa_id INT PRIMARY KEY,
            capa_organisation_id INT,
            responsible_person_id INT,
            employee_organisation_id INT,
            repaired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    capa_ids = [r[0] for r in rows]
    for capa_id, capa_org, emp_id, emp_org in rows:
        cur.execute(
            """
            INSERT INTO _capa_assignee_mismatch_backup
                (capa_id, capa_organisation_id, responsible_person_id, employee_organisation_id)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                responsible_person_id = VALUES(responsible_person_id),
                employee_organisation_id = VALUES(employee_organisation_id)
            """,
            (capa_id, capa_org, emp_id, emp_org),
        )

    format_ids = ",".join(["%s"] * len(capa_ids))
    cur.execute(
        f"UPDATE capa_actions SET responsible_person_id = NULL WHERE id IN ({format_ids})",
        capa_ids,
    )

    conn.commit()
    print(f"\nBacked up and cleared responsible_person_id on {len(rows)} capa_actions rows.")
    print("Backup table: _capa_assignee_mismatch_backup")


if __name__ == "__main__":
    main()
