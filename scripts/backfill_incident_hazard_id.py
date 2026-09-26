"""One-off seed-data completion: assign a hazard_id to incidents that don't
have one, so per-org "Top Incident Categories" charts aren't empty.

IMPORTANT — this is NOT a causal analysis. There is no real signal in this
seed data to determine which specific hazard actually caused each historical
incident: even org 1's incidents, which already carry a hazard_id, all share
the literal placeholder description "Incident description for testing." —
that existing linkage is itself an arbitrary seed assignment, not the result
of real investigation. This script does the same kind of assignment for the
orgs that never got one (org 2, org 3) or had theirs cleared by
repair_reference_org_mismatch.py for pointing at another org's hazard
(org 4): each affected incident is deterministically assigned one of its
OWN org's hazards, cycling through that org's hazard list by incident id so
the assignment is reproducible and spreads evenly across categories.

If this ever needs to mean something more than "the chart isn't empty" —
e.g. before treating category counts as a real finding — the right fix is
collecting hazard_id at report time (now required, see
app/schemas/incident_workflow.py WorkerIncidentReport) so future incidents
carry a real link, not running this again.

Non-destructive: every assignment is recorded in
_incident_hazard_backfill_log, and the script only touches incidents.hazard_id
where it is currently NULL — it never overwrites an existing value.

Usage:
    python scripts/backfill_incident_hazard_id.py            # dry run
    python scripts/backfill_incident_hazard_id.py --apply    # apply
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
        "SELECT id, organisation_id FROM incidents WHERE hazard_id IS NULL AND organisation_id IS NOT NULL ORDER BY organisation_id, id"
    )
    incidents = cur.fetchall()

    cur.execute("SELECT organisation_id, id FROM hazards ORDER BY organisation_id, id")
    hazards_by_org = {}
    for org_id, hazard_id in cur.fetchall():
        hazards_by_org.setdefault(org_id, []).append(hazard_id)

    plan = []
    skipped_no_hazards = []
    counters = {}
    for inc_id, org_id in incidents:
        org_hazards = hazards_by_org.get(org_id)
        if not org_hazards:
            skipped_no_hazards.append((inc_id, org_id))
            continue
        i = counters.get(org_id, 0)
        plan.append((inc_id, org_id, org_hazards[i % len(org_hazards)]))
        counters[org_id] = i + 1
    return plan, skipped_no_hazards


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually write changes. Without this flag, only reports what would change.")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    plan, skipped = build_plan(cur)

    by_org = {}
    for inc_id, org_id, hazard_id in plan:
        by_org[org_id] = by_org.get(org_id, 0) + 1
    for org_id, count in sorted(by_org.items()):
        print(f"org {org_id}: {count} incidents would get a hazard_id assigned")
    if skipped:
        print(f"skipped (org has no hazards at all): {len(skipped)} incidents -> {skipped}")

    if not plan:
        print("\nNothing to backfill.")
        return

    if not args.apply:
        print(f"\nDry run only — {len(plan)} rows would be updated. Re-run with --apply to write these changes.")
        return

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS _incident_hazard_backfill_log (
            incident_id INT PRIMARY KEY,
            organisation_id INT,
            assigned_hazard_id INT,
            backfilled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()

    for inc_id, org_id, hazard_id in plan:
        cur.execute(
            "UPDATE incidents SET hazard_id = %s WHERE id = %s AND hazard_id IS NULL",
            (hazard_id, inc_id),
        )
        cur.execute(
            """
            INSERT INTO _incident_hazard_backfill_log (incident_id, organisation_id, assigned_hazard_id)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE assigned_hazard_id = VALUES(assigned_hazard_id)
            """,
            (inc_id, org_id, hazard_id),
        )
    conn.commit()
    print(f"\nBackfilled hazard_id on {len(plan)} incidents.")
    print("Log table: _incident_hazard_backfill_log")


if __name__ == "__main__":
    main()
