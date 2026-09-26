"""One-off data repair: working_stations.site_id is cross-org contaminated.

The last of the global-PK reference problems found by the dashboard audits, and
the only one that cannot be fixed automatically. A station in one org points at
another org's `sites` row, so every org-scoped join through Site returns
nothing — which is why the Risk Heatmap ("zone risk" on /analytics/risk-summary,
and the same panel on the manager app) is empty for orgs 2, 3 and 4 no matter
how many incidents are reported against those stations.

Why neither existing strategy works here:

  * NULL-out, as repair_reference_org_mismatch.py does for
    incidents.location_station_id — blocked: working_stations.site_id is
    NOT NULL.

  * Name-remap, as repair_hazard_category_org_mismatch.py does for
    hazards.category_id — blocked: there is not one same-name site in the
    owning org for ANY of the 83 mismatched stations. Org 1 has "Sheffield
    Components Manufacturing Plant"; org 4's stations would need to map to
    "Bridgend Manufacturing Complex" or "WindTech Nacelle Manufacturing Ltd".
    The names have nothing in common, so there is no automatic match to make.

Nothing on the station row says which site it belongs to either — `department`
and `zone_classification` are internal groupings, not sites. Choosing among the
owning org's sites is therefore a judgement about the physical estate, and the
wrong choice is worse than the empty chart it replaces: the heatmap would show
confident but invented zone attributions that read as fact.

So this script diagnoses by default and only writes when told exactly what to
write. Run it with no arguments to see the mismatch and each org's candidate
sites, then re-run with the site you have chosen:

    python scripts/repair_working_station_site_org_mismatch.py
    python scripts/repair_working_station_site_org_mismatch.py --org 4 --site-id 10 --apply

Note before choosing: org 4 currently holds eight rows all named "Bridgend
Manufacturing Complex" (ids 10-17). Those duplicates are worth resolving first —
mapping 32 stations onto one arbitrary copy of a site that exists eight times
buries the duplication rather than fixing it.

The previous site_id of every row written is copied into
_working_station_site_backup first, so a bad choice can be reversed.
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


def report(cur) -> None:
    cur.execute(
        """
        SELECT ws.organisation_id, s.organisation_id, COUNT(*)
          FROM working_stations ws
          JOIN sites s ON s.id = ws.site_id
         WHERE ws.organisation_id <> s.organisation_id
      GROUP BY 1, 2
      ORDER BY 1, 2
        """
    )
    rows = cur.fetchall()
    if not rows:
        print("No cross-org working_stations.site_id references. Nothing to repair.")
        return

    total = sum(r[2] for r in rows)
    print(f"working_stations.site_id: {total} stations point at another org's site\n")
    for ws_org, site_org, n in rows:
        print(f"  org {ws_org}: {n:3} stations -> sites owned by org {site_org}")

    affected = sorted({r[0] for r in rows})
    print("\nCandidate sites in each affected org — pick one per org:\n")
    for org in affected:
        cur.execute(
            "SELECT id, site_name, city FROM sites WHERE organisation_id = %s ORDER BY id",
            (org,),
        )
        sites = cur.fetchall()
        print(f"  org {org}:")
        if not sites:
            print("     (no sites of its own — one must be created before any repair)")
        for sid, name, city in sites:
            print(f"     --site-id {sid:<5} {name}  ({city})")
        print()

    print("Re-run with --org <n> --site-id <id> --apply once you have chosen.")


def apply_remap(cur, org: int, site_id: int) -> int:
    cur.execute(
        "SELECT id, organisation_id FROM sites WHERE id = %s", (site_id,)
    )
    site = cur.fetchone()
    if not site:
        raise SystemExit(f"No site with id {site_id}.")
    if site[1] != org:
        raise SystemExit(
            f"Site {site_id} belongs to org {site[1]}, not org {org}. "
            "Repointing to it would recreate the very mismatch this repairs."
        )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS _working_station_site_backup (
            station_id      INT NOT NULL,
            organisation_id INT,
            old_site_id     INT,
            new_site_id     INT,
            repaired_at     DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        SELECT ws.id, ws.organisation_id, ws.site_id
          FROM working_stations ws
          JOIN sites s ON s.id = ws.site_id
         WHERE ws.organisation_id = %s AND ws.organisation_id <> s.organisation_id
        """,
        (org,),
    )
    targets = cur.fetchall()
    if not targets:
        print(f"org {org}: no mismatched stations. Nothing written.")
        return 0

    for station_id, station_org, old_site in targets:
        cur.execute(
            "INSERT INTO _working_station_site_backup "
            "(station_id, organisation_id, old_site_id, new_site_id) VALUES (%s, %s, %s, %s)",
            (station_id, station_org, old_site, site_id),
        )
        cur.execute(
            "UPDATE working_stations SET site_id = %s WHERE id = %s", (site_id, station_id)
        )
    return len(targets)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--org", type=int, help="Organisation whose stations to repoint")
    ap.add_argument("--site-id", type=int, help="Site in that org to point them at")
    ap.add_argument("--apply", action="store_true", help="Write the change")
    args = ap.parse_args()

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if not args.apply:
                report(cur)
                if args.org or args.site_id:
                    print("(--org/--site-id ignored without --apply)")
                return
            if not (args.org and args.site_id):
                raise SystemExit("--apply needs both --org and --site-id. Run with no arguments first.")
            n = apply_remap(cur, args.org, args.site_id)
        conn.commit()
        print(f"Repointed {n} stations in org {args.org} to site {args.site_id}.")
        print("Backup table: _working_station_site_backup")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
