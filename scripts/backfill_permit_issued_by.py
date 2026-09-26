"""One-off seed-data completion: assign issued_by on permits that lost it to
repair_employee_ref_org_mismatch.py (which correctly nulled ~15,490 cross-org
references, including these), so contractor-scoped views — the Vendors page's
"Contractor Exposure Hours" chart and "Permit Violations" list — aren't
empty for every org.

IMPORTANT — same caveat as backfill_incident_hazard_id.py: there is no real
signal in this seed data for who actually issued each historical permit. This
is seed-data completion, not a claim about who really issued what.

Assignment rule, per org:
  - Org has contractor employees (employment_type LIKE '%contractor%'):
    round-robin across that org's contractors — matches how this codebase
    already treats permits_to_work.issued_by (app/controllers/vendor.py
    filters "contractor permits" by issued_by IN contractor_ids).
  - Org has no contractors (e.g. org 3): round-robin across that org's
    employees generally — there is no contractor to attribute it to.

Only touches permits_to_work.issued_by where it is currently NULL — never
overwrites an existing value. Every assignment is logged in
_permit_issued_by_backfill_log for traceability.

Usage:
    python scripts/backfill_permit_issued_by.py            # dry run
    python scripts/backfill_permit_issued_by.py --apply    # apply
"""
import argparse
import os

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


def build_plan(cur):
    cur.execute(
        "SELECT id, organisation_id FROM permits_to_work WHERE issued_by IS NULL AND organisation_id IS NOT NULL ORDER BY organisation_id, id"
    )
    permits = cur.fetchall()

    cur.execute(
        "SELECT organisation_id, id FROM employees WHERE employment_type LIKE %s ORDER BY organisation_id, id",
        ("%contractor%",),
    )
    contractors_by_org = {}
    for org_id, emp_id in cur.fetchall():
        contractors_by_org.setdefault(org_id, []).append(emp_id)

    cur.execute("SELECT organisation_id, id FROM employees ORDER BY organisation_id, id")
    all_employees_by_org = {}
    for org_id, emp_id in cur.fetchall():
        all_employees_by_org.setdefault(org_id, []).append(emp_id)

    plan = []
    skipped_no_employees = []
    counters = {}
    for permit_id, org_id in permits:
        pool = contractors_by_org.get(org_id) or all_employees_by_org.get(org_id)
        if not pool:
            skipped_no_employees.append((permit_id, org_id))
            continue
        i = counters.get(org_id, 0)
        plan.append((permit_id, org_id, pool[i % len(pool)]))
        counters[org_id] = i + 1
    return plan, skipped_no_employees


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually write changes. Without this flag, only reports what would change.")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    plan, skipped = build_plan(cur)

    by_org = {}
    for permit_id, org_id, emp_id in plan:
        by_org[org_id] = by_org.get(org_id, 0) + 1
    for org_id, count in sorted(by_org.items()):
        print(f"org {org_id}: {count} permits would get issued_by assigned")
    if skipped:
        print(f"skipped (org has no employees at all): {len(skipped)} permits")

    if not plan:
        print("\nNothing to backfill.")
        return

    if not args.apply:
        print(f"\nDry run only — {len(plan)} rows would be updated. Re-run with --apply to write these changes.")
        return

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS _permit_issued_by_backfill_log (
            permit_id INT PRIMARY KEY,
            organisation_id INT,
            assigned_employee_id INT,
            backfilled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()

    for permit_id, org_id, emp_id in plan:
        cur.execute(
            "UPDATE permits_to_work SET issued_by = %s WHERE id = %s AND issued_by IS NULL",
            (emp_id, permit_id),
        )
        cur.execute(
            """
            INSERT INTO _permit_issued_by_backfill_log (permit_id, organisation_id, assigned_employee_id)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE assigned_employee_id = VALUES(assigned_employee_id)
            """,
            (permit_id, org_id, emp_id),
        )
    conn.commit()
    print(f"\nBackfilled issued_by on {len(plan)} permits.")
    print("Log table: _permit_issued_by_backfill_log")


if __name__ == "__main__":
    main()
