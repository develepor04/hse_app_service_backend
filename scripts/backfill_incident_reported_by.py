"""One-off seed-data completion: assign reported_by on incidents that lost it
to repair_employee_ref_org_mismatch.py (which correctly nulled cross-org
references, including these), so the Violations page's "Reported By
(Employment Type)" chart isn't empty for every org.

IMPORTANT — same caveat as backfill_incident_hazard_id.py and
backfill_permit_issued_by.py: there is no real signal in this seed data for
who actually reported each historical incident. This is seed-data
completion, not a claim about who really reported what.

Assignment rule, per org: round-robin across that org's employees, cycling
by incident id so the assignment is reproducible.

Only touches incidents.reported_by where it is currently NULL — never
overwrites an existing value. Every assignment is logged in
_incident_reported_by_backfill_log for traceability.

Usage:
    python scripts/backfill_incident_reported_by.py            # dry run
    python scripts/backfill_incident_reported_by.py --apply    # apply
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


def build_plan(cur, org_id=None):
    if org_id is not None:
        cur.execute(
            "SELECT id, organisation_id FROM incidents WHERE reported_by IS NULL AND organisation_id = %s ORDER BY id",
            (org_id,),
        )
    else:
        cur.execute(
            "SELECT id, organisation_id FROM incidents WHERE reported_by IS NULL AND organisation_id IS NOT NULL ORDER BY organisation_id, id"
        )
    incidents = cur.fetchall()

    cur.execute("SELECT organisation_id, id FROM employees ORDER BY organisation_id, id")
    employees_by_org = {}
    for org_id, emp_id in cur.fetchall():
        employees_by_org.setdefault(org_id, []).append(emp_id)

    plan = []
    skipped_no_employees = []
    counters = {}
    for inc_id, org_id in incidents:
        pool = employees_by_org.get(org_id)
        if not pool:
            skipped_no_employees.append((inc_id, org_id))
            continue
        i = counters.get(org_id, 0)
        plan.append((inc_id, org_id, pool[i % len(pool)]))
        counters[org_id] = i + 1
    return plan, skipped_no_employees


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually write changes. Without this flag, only reports what would change.")
    parser.add_argument("--org-id", type=int, default=None, help="Restrict to a single organisation_id. Without this, all orgs are covered.")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    plan, skipped = build_plan(cur, org_id=args.org_id)

    by_org = {}
    for inc_id, org_id, emp_id in plan:
        by_org[org_id] = by_org.get(org_id, 0) + 1
    for org_id, count in sorted(by_org.items()):
        print(f"org {org_id}: {count} incidents would get reported_by assigned")
    if skipped:
        print(f"skipped (org has no employees at all): {len(skipped)} incidents -> {skipped}")

    if not plan:
        print("\nNothing to backfill.")
        return

    if not args.apply:
        print(f"\nDry run only — {len(plan)} rows would be updated. Re-run with --apply to write these changes.")
        return

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS _incident_reported_by_backfill_log (
            incident_id INT PRIMARY KEY,
            organisation_id INT,
            assigned_employee_id INT,
            backfilled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()

    for inc_id, org_id, emp_id in plan:
        cur.execute(
            "UPDATE incidents SET reported_by = %s WHERE id = %s AND reported_by IS NULL",
            (emp_id, inc_id),
        )
        cur.execute(
            """
            INSERT INTO _incident_reported_by_backfill_log (incident_id, organisation_id, assigned_employee_id)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE assigned_employee_id = VALUES(assigned_employee_id)
            """,
            (inc_id, org_id, emp_id),
        )
    conn.commit()
    print(f"\nBackfilled reported_by on {len(plan)} incidents.")
    print("Log table: _incident_reported_by_backfill_log")


if __name__ == "__main__":
    main()
