"""One-off data repair: hazards.category_id is NOT NULL and, like every other
global-PK reference found this session, is cross-org contaminated — a hazard
in one org can point at another org's hazard_categories row. This is what
kept "Top Incident Categories" empty for org 2/3/4 even after incidents.hazard_id
was backfilled: the join chain incident -> hazard -> category broke one hop
later than expected.

Same remap strategy as repair_reference_org_mismatch.py's permit_type_id fix:
category_id can't be nulled (NOT NULL), so each mismatched hazard is repointed
to the SAME-name category belonging to its own org, when one exists. Org 3
uses different category names entirely (Fire & Explosion vs Fire/Explosion,
Working at Height vs Fall/Height, etc.) so some of its hazards have no safe
automatic match — those are reported and left untouched.

Usage:
    python scripts/repair_hazard_category_org_mismatch.py            # dry run
    python scripts/repair_hazard_category_org_mismatch.py --apply    # apply
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


def plan_remap(cur):
    cur.execute("SELECT organisation_id, id, category_name FROM hazard_categories")
    by_org = {}
    for org, cid, name in cur.fetchall():
        by_org.setdefault(org, {})[name] = cid

    cur.execute(
        """
        SELECT h.id, h.organisation_id, h.category_id, c.category_name
        FROM hazards h JOIN hazard_categories c ON h.category_id = c.id
        WHERE h.organisation_id IS NOT NULL AND c.organisation_id IS NOT NULL
          AND h.organisation_id != c.organisation_id
        """
    )
    remappable, unmappable = [], []
    for hazard_id, org_id, old_cat_id, wrong_name in cur.fetchall():
        new_id = by_org.get(org_id, {}).get(wrong_name)
        if new_id:
            remappable.append((hazard_id, org_id, old_cat_id, new_id))
        else:
            unmappable.append((hazard_id, org_id, old_cat_id, wrong_name))
    return remappable, unmappable


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    remappable, unmappable = plan_remap(cur)
    print(f"hazards.category_id: {len(remappable)} remappable by name, {len(unmappable)} with no same-org name match")
    if unmappable:
        print("  unmappable:", unmappable)

    if not remappable:
        print("\nNothing to remap.")
        return

    if not args.apply:
        print(f"\nDry run only — {len(remappable)} rows would be remapped. Re-run with --apply to write these changes.")
        return

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS _hazard_category_remap_backup (
            hazard_id INT PRIMARY KEY,
            organisation_id INT,
            old_category_id INT,
            new_category_id INT,
            repaired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()

    for hazard_id, org_id, old_cat_id, new_cat_id in remappable:
        cur.execute(
            """
            INSERT INTO _hazard_category_remap_backup (hazard_id, organisation_id, old_category_id, new_category_id)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE old_category_id = VALUES(old_category_id), new_category_id = VALUES(new_category_id)
            """,
            (hazard_id, org_id, old_cat_id, new_cat_id),
        )
        cur.execute("UPDATE hazards SET category_id = %s WHERE id = %s", (new_cat_id, hazard_id))
    conn.commit()
    print(f"\nRemapped {len(remappable)} hazards.category_id references.")
    print("Backup table: _hazard_category_remap_backup")


if __name__ == "__main__":
    main()
