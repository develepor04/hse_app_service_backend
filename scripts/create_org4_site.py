"""One-off data repair: org 4 ("WindTech Nacelle Manufacturing Ltd") has zero
Site rows, so all 32 of its working_stations.site_id values were cross-org
corrupted (site_id is NOT NULL, so they could never have been cleared like
the other repairs this session — there was nothing valid to point them at).

Creates one Site for org 4 (mirroring org 2's single-site setup for the same
company name — a different tenant, so its own Site row, not a shared one),
then repoints all of org 4's working_stations at it.

Non-destructive: the old (wrong-org) site_id on each station is recorded in
_org4_site_backfill_log before being overwritten.

Usage:
    python scripts/create_org4_site.py            # dry run
    python scripts/create_org4_site.py --apply    # apply
"""
import argparse
import os

import pymysql
from dotenv import load_dotenv

load_dotenv()

ORG_ID = 4
NEW_SITE = {
    "site_name": "Grimsby Nacelle Manufacturing Complex",
    "address": "Europarc Industrial Estate, Grimsby",
    "postcode": "DN37 9TU",
    "city": "North East Lincolnshire",
    "type": "Manufacturing & Assembly",
    "operational_status": "Active",
    "number_of_working_stations": 32,
    "capacity": 150,
    "primary_products": "Wind Turbine Nacelles",
    "hazard_classification": "High Risk",
}


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

    cur.execute("SELECT COUNT(*) FROM sites WHERE organisation_id = %s", (ORG_ID,))
    existing = cur.fetchone()[0]
    if existing:
        print(f"org {ORG_ID} already has {existing} site(s) — nothing to do.")
        return

    cur.execute(
        "SELECT id, site_id FROM working_stations WHERE organisation_id = %s",
        (ORG_ID,),
    )
    stations = cur.fetchall()
    print(f"Would create 1 site for org {ORG_ID} ({NEW_SITE['site_name']}) "
          f"and repoint {len(stations)} working_stations to it.")

    if not args.apply:
        print("\nDry run only. Re-run with --apply to write these changes.")
        return

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS _org4_site_backfill_log (
            working_station_id INT PRIMARY KEY,
            old_site_id INT,
            new_site_id INT,
            backfilled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()

    cur.execute(
        """
        INSERT INTO sites
            (site_name, address, postcode, city, type, operational_status,
             number_of_working_stations, capacity, primary_products,
             hazard_classification, organisation_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            NEW_SITE["site_name"], NEW_SITE["address"], NEW_SITE["postcode"],
            NEW_SITE["city"], NEW_SITE["type"], NEW_SITE["operational_status"],
            NEW_SITE["number_of_working_stations"], NEW_SITE["capacity"],
            NEW_SITE["primary_products"], NEW_SITE["hazard_classification"], ORG_ID,
        ),
    )
    new_site_id = cur.lastrowid
    conn.commit()
    print(f"Created site id={new_site_id}: {NEW_SITE['site_name']}")

    for station_id, old_site_id in stations:
        cur.execute(
            """
            INSERT INTO _org4_site_backfill_log (working_station_id, old_site_id, new_site_id)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE old_site_id = VALUES(old_site_id), new_site_id = VALUES(new_site_id)
            """,
            (station_id, old_site_id, new_site_id),
        )
        cur.execute(
            "UPDATE working_stations SET site_id = %s WHERE id = %s",
            (new_site_id, station_id),
        )
    conn.commit()
    print(f"Repointed {len(stations)} working_stations to site {new_site_id}.")
    print("Backup table: _org4_site_backfill_log")


if __name__ == "__main__":
    main()
