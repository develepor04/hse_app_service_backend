"""One-off seed-data completion: assign a location_station_id to org 4's
incidents, which lost theirs to repair_reference_org_mismatch.py (100% were
cross-org corrupted, same as incidents.hazard_id — see
backfill_incident_hazard_id.py for the same caveat: this is not a claim about
which station each incident actually happened at, just spreading them across
org 4's own stations, now that create_org4_site.py has given it real ones,
so zone/site widgets aren't empty).

Deterministic round-robin, org 4 only — org 2 and org 3 have the same gap but
their own working_stations.site_id is still cross-org-mismatched (unfixed),
so backfilling their incidents now would only be internally consistent, not
zone-accurate. Handle those after their station->site links are repaired.

Usage:
    python scripts/backfill_incident_location_station.py            # dry run
    python scripts/backfill_incident_location_station.py --apply    # apply
"""
import argparse
import os

import pymysql
from dotenv import load_dotenv

load_dotenv()

ORG_ID = 4


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
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT id FROM incidents WHERE organisation_id = %s AND location_station_id IS NULL ORDER BY id",
        (ORG_ID,),
    )
    incident_ids = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT id FROM working_stations WHERE organisation_id = %s ORDER BY id", (ORG_ID,))
    station_ids = [r[0] for r in cur.fetchall()]

    print(f"org {ORG_ID}: {len(incident_ids)} incidents missing location_station_id, {len(station_ids)} stations available")

    if not incident_ids or not station_ids:
        print("Nothing to backfill.")
        return

    if not args.apply:
        print(f"\nDry run only — {len(incident_ids)} rows would be updated. Re-run with --apply to write these changes.")
        return

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS _incident_location_backfill_log (
            incident_id INT PRIMARY KEY,
            organisation_id INT,
            assigned_station_id INT,
            backfilled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()

    for i, inc_id in enumerate(incident_ids):
        station_id = station_ids[i % len(station_ids)]
        cur.execute(
            "UPDATE incidents SET location_station_id = %s WHERE id = %s AND location_station_id IS NULL",
            (station_id, inc_id),
        )
        cur.execute(
            """
            INSERT INTO _incident_location_backfill_log (incident_id, organisation_id, assigned_station_id)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE assigned_station_id = VALUES(assigned_station_id)
            """,
            (inc_id, ORG_ID, station_id),
        )
    conn.commit()
    print(f"\nBackfilled location_station_id on {len(incident_ids)} incidents.")
    print("Log table: _incident_location_backfill_log")


if __name__ == "__main__":
    main()
