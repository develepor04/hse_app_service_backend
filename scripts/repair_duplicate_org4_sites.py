"""One-off data repair: org 4's site list is one real site and eight empty copies.

What the `sites` table holds for org 4:

  * id 9  — "WindTech Nacelle Manufacturing Ltd". Every piece of real data hangs
    off this row: 32 working stations, 7 audits. But its columns are shifted by
    one — company-level values were written into site-level fields, so it reads
    address "United Kingdom", postcode "Renewable Energy - W", city "150", type
    "Bridgend, Wales" and operational_status "WindTech Group Plc". Its name is
    the company's, not a site's.

  * ids 10-17 — eight byte-identical rows all named "Bridgend Manufacturing
    Complex", each well-formed but holding nothing: no stations, no audits. A
    seed script that was run nine times.

The visible symptom is the Audit Programme page, which lists one row per site
and so prints "Bridgend Manufacturing Complex" eight times over. It looks like a
rendering bug and is not one — the programme is correctly showing eight sites
that should never have existed.

The repair keeps the row with the data and takes the field values from the
well-formed copies, which is the only place a correct address, postcode and
hazard classification for this site exists. Site 9 is renamed to a site name
rather than the company name; the company is already on the `organisation`
record and repeating it here is what made the two indistinguishable.

Not done as a migration on purpose. Migrations run everywhere, and this is one
organisation's seed accident — running it against a real estate would delete
real sites. It is a tool you point at a database, once, deliberately.

Every row deleted is copied into _org4_site_backup first, so this is reversible.
"""
import argparse
import os

import pymysql
from dotenv import load_dotenv

load_dotenv()

ORG = 4
KEEP = 9                     # the row that owns the stations and audits
DROP = tuple(range(10, 18))  # the eight empty copies

# Taken from the well-formed duplicates. These are this site's real details —
# site 9 never had them, because its columns hold the company's instead.
CORRECTED = {
    "site_name": "Bridgend Nacelle Plant",
    "address": "Industrial Estate, Bridgend",
    "postcode": "CF31 3TR",
    "city": "Bridgend",
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


def report(cur) -> None:
    cur.execute(
        "SELECT id, site_name, "
        "  (SELECT COUNT(*) FROM working_stations w WHERE w.site_id = s.id), "
        "  (SELECT COUNT(*) FROM audits a WHERE a.site_id = s.id) "
        "FROM sites s WHERE s.organisation_id = %s ORDER BY s.id",
        (ORG,),
    )
    rows = cur.fetchall()
    print(f"org {ORG}: {len(rows)} sites")
    for sid, name, stations, audits in rows:
        mark = "KEEP " if sid == KEEP else ("drop " if sid in DROP else "     ")
        print(f"  {mark} {sid:>3}  {name:<38} stations={stations:<3} audits={audits}")

    cur.execute(
        "SELECT COUNT(*) FROM checklist_submissions WHERE site_id IN %s", (DROP,)
    )
    print(f"\nchecklist_submissions pointing at a dropped site: {cur.fetchone()[0]}"
          f"  (repointed to site {KEEP}, not deleted)")
    cur.execute("SELECT COUNT(*) FROM audit_programme WHERE site_id IN %s", (DROP,))
    print(f"audit_programme rows for dropped sites:            {cur.fetchone()[0]}")
    print("\nRun again with --apply to write.")


def apply_repair(cur) -> dict:
    cur.execute(
        "CREATE TABLE IF NOT EXISTS _org4_site_backup ("
        " id INT, site_name VARCHAR(255), address VARCHAR(255), postcode VARCHAR(64),"
        " city VARCHAR(128), type VARCHAR(128), operational_status VARCHAR(64),"
        " number_of_working_stations INT, capacity INT, primary_products VARCHAR(255),"
        " hazard_classification VARCHAR(64), organisation_id INT,"
        " backed_up_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    cur.execute(
        "INSERT INTO _org4_site_backup "
        "(id, site_name, address, postcode, city, type, operational_status,"
        " number_of_working_stations, capacity, primary_products,"
        " hazard_classification, organisation_id) "
        "SELECT id, site_name, address, postcode, city, type, operational_status,"
        " number_of_working_stations, capacity, primary_products,"
        " hazard_classification, organisation_id "
        "FROM sites WHERE organisation_id = %s AND id IN %s",
        (ORG, DROP + (KEEP,)),
    )

    # Anything still pointing at a doomed site moves to the real one rather than
    # being deleted with it — a draft checklist is somebody's work.
    cur.execute(
        "UPDATE checklist_submissions SET site_id = %s WHERE site_id IN %s", (KEEP, DROP)
    )
    repointed = cur.rowcount

    cur.execute("DELETE FROM audit_programme WHERE site_id IN %s", (DROP,))
    programme_removed = cur.rowcount

    cur.execute("DELETE FROM sites WHERE organisation_id = %s AND id IN %s", (ORG, DROP))
    sites_removed = cur.rowcount

    sets = ", ".join(f"{k} = %s" for k in CORRECTED)
    cur.execute(
        f"UPDATE sites SET {sets} WHERE id = %s", (*CORRECTED.values(), KEEP)
    )

    # audit_programme keeps its own copy of the name, which is what the Programme
    # page actually renders. Refreshing the site row alone would leave the page
    # showing the old one.
    cur.execute(
        "UPDATE audit_programme SET site_name = %s WHERE site_id = %s",
        (CORRECTED["site_name"], KEEP),
    )

    return {
        "repointed_checklists": repointed,
        "programme_rows_removed": programme_removed,
        "sites_removed": sites_removed,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Write the change")
    args = ap.parse_args()

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if not args.apply:
                report(cur)
                return
            out = apply_repair(cur)
        conn.commit()
        print(f"Repointed {out['repointed_checklists']} checklist submission(s) to site {KEEP}.")
        print(f"Removed {out['programme_rows_removed']} programme row(s) and "
              f"{out['sites_removed']} duplicate site(s).")
        print(f"Site {KEEP} corrected and renamed to \"{CORRECTED['site_name']}\".")
        print("Backup table: _org4_site_backup")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
