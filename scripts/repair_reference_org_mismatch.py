"""One-off data repair: fix reference-table FK columns on tenant-owned
records where the referenced row belongs to a different organisation.

Same root cause and pattern as repair_employee_ref_org_mismatch.py, found
during a dashboard audit: working_stations, hazards, and permit_types are
themselves org-owned (each org defines its own sites/hazards/permit types),
and their ids are a global, cross-tenant primary key — so a tenant record
referencing one by id can end up pointing at another org's row. Reads are
already defended (app/utils/tenant.py org_scoped_join), but the raw columns
still carry the wrong reference.

Two repair strategies, because the columns don't all behave the same:

  1. NULL-out (nullable columns) — the reference is simply cleared:
       incidents.location_station_id      -> working_stations
       incidents.hazard_id                -> hazards
       safety_walks.location_station_id   -> working_stations
       near_misses.location_station_id    -> working_stations
       permits_to_work.location_station_id -> working_stations

  2. Name-remap (permits_to_work.permit_type_id) — this column is NOT NULL
     (fk_ptw_permit_type), so it can't be cleared. Instead, for each
     mismatched row, look up the wrong-org permit_type's name and repoint to
     the SAME-name permit_type that belongs to the record's own org, when one
     exists. ~80% of mismatches have an exact-name counterpart (Hot Work
     Permit, Confined Space Entry, etc. are named identically across every
     org's permit_types). The remainder (org 3's permits referencing 5 permit
     type names org 3 never defined — Equipment Isolation/Lockout,
     Excavation/Digging, Cold Work, Chemical Application, Testing &
     Commissioning) have no safe automatic mapping and are left untouched;
     the script reports them so someone can decide whether org 3 should gain
     those permit_type rows or the permits should be reclassified by hand.

Non-destructive: every value touched (including for the remap path — the
row's OLD permit_type_id) is copied into _reference_mismatch_backup first, so
any of it can be restored.

Commits after each table/column so a failure partway through does not roll
back repairs that already succeeded.

Usage:
    python scripts/repair_reference_org_mismatch.py            # dry run
    python scripts/repair_reference_org_mismatch.py --apply    # apply
"""
import argparse
import os

import pymysql
from dotenv import load_dotenv

load_dotenv()

# (table, org_column, fk_column, ref_table) — NULL-out path only.
NULL_TARGETS = [
    ("incidents", "organisation_id", "location_station_id", "working_stations"),
    ("incidents", "organisation_id", "hazard_id", "hazards"),
    ("safety_walks", "organisation_id", "location_station_id", "working_stations"),
    ("near_misses", "organisation_id", "location_station_id", "working_stations"),
    ("permits_to_work", "organisation_id", "location_station_id", "working_stations"),
]


def get_connection():
    return pymysql.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "hse_db"),
    )


def find_mismatches(cur, table, org_col, fk_col, ref_table):
    cur.execute(
        f"""
        SELECT t.id, t.{org_col}, t.{fk_col}, r.organisation_id
        FROM {table} t
        JOIN {ref_table} r ON t.{fk_col} = r.id
        WHERE t.{org_col} IS NOT NULL AND r.organisation_id IS NOT NULL
          AND t.{org_col} != r.organisation_id
        """
    )
    return cur.fetchall()


def ensure_backup_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS _reference_mismatch_backup (
            table_name VARCHAR(64) NOT NULL,
            row_id INT NOT NULL,
            column_name VARCHAR(64) NOT NULL,
            ref_table VARCHAR(64) NOT NULL,
            old_ref_id INT,
            new_ref_id INT NULL COMMENT 'set only for a remap, not a null-out',
            record_organisation_id INT,
            ref_organisation_id INT,
            repaired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (table_name, row_id, column_name)
        )
        """
    )


def backup_rows(cur, table, fk_col, ref_table, rows, new_ref_id=None):
    for row_id, rec_org, ref_id, ref_org in rows:
        cur.execute(
            """
            INSERT INTO _reference_mismatch_backup
                (table_name, row_id, column_name, ref_table, old_ref_id, new_ref_id, record_organisation_id, ref_organisation_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                old_ref_id = VALUES(old_ref_id),
                new_ref_id = VALUES(new_ref_id),
                record_organisation_id = VALUES(record_organisation_id),
                ref_organisation_id = VALUES(ref_organisation_id)
            """,
            (table, row_id, fk_col, ref_table, ref_id, new_ref_id, rec_org, ref_org),
        )


def plan_permit_type_remap(cur):
    """Return (remappable, unmappable) where remappable is a list of
    (row_id, org_id, old_type_id, new_type_id) and unmappable is a list of
    (row_id, org_id, old_type_id, wrong_name) with no same-org name match."""
    cur.execute("SELECT organisation_id, id, permit_type_name FROM permit_types")
    by_org = {}
    for org, pid, name in cur.fetchall():
        by_org.setdefault(org, {})[name] = pid

    cur.execute(
        """
        SELECT p.id, p.organisation_id, p.permit_type_id, t.permit_type_name
        FROM permits_to_work p JOIN permit_types t ON p.permit_type_id = t.id
        WHERE p.organisation_id IS NOT NULL AND t.organisation_id IS NOT NULL
          AND p.organisation_id != t.organisation_id
        """
    )
    remappable, unmappable = [], []
    for row_id, org_id, old_type_id, wrong_name in cur.fetchall():
        new_id = by_org.get(org_id, {}).get(wrong_name)
        if new_id:
            remappable.append((row_id, org_id, old_type_id, new_id))
        else:
            unmappable.append((row_id, org_id, old_type_id, wrong_name))
    return remappable, unmappable


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually write changes. Without this flag, only reports what would change.")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    null_plan = []
    total = 0
    for table, org_col, fk_col, ref_table in NULL_TARGETS:
        rows = find_mismatches(cur, table, org_col, fk_col, ref_table)
        null_plan.append((table, org_col, fk_col, ref_table, rows))
        total += len(rows)
        print(f"{table}.{fk_col} -> {ref_table}: {len(rows)} mismatched rows (will be cleared)")

    remappable, unmappable = plan_permit_type_remap(cur)
    print(f"permits_to_work.permit_type_id -> permit_types: {len(remappable)} mismatched rows (will be remapped by name), "
          f"{len(unmappable)} with no same-org name match (left as-is)")
    if unmappable:
        from collections import Counter
        counts = Counter(name for *_, name in unmappable)
        print("  unmappable names:", dict(counts))

    if total == 0 and not remappable:
        print("\nNo repairable mismatches found. Nothing to do.")
        return

    if not args.apply:
        print(f"\nDry run only — {total} rows would be cleared, {len(remappable)} would be remapped. "
              "Re-run with --apply to back up and write these changes.")
        return

    ensure_backup_table(cur)
    conn.commit()

    grand_total = 0
    for table, org_col, fk_col, ref_table, rows in null_plan:
        if not rows:
            continue
        backup_rows(cur, table, fk_col, ref_table, rows)
        row_ids = [r[0] for r in rows]
        placeholders = ",".join(["%s"] * len(row_ids))
        cur.execute(
            f"UPDATE {table} SET {fk_col} = NULL WHERE id IN ({placeholders})",
            row_ids,
        )
        conn.commit()
        print(f"Cleared {table}.{fk_col} on {len(rows)} rows.")
        grand_total += len(rows)

    if remappable:
        backup_rows(
            cur, "permits_to_work", "permit_type_id", "permit_types",
            [(row_id, org_id, old_id, None) for row_id, org_id, old_id, _new_id in remappable],
        )
        # Group by new_id so each UPDATE targets rows that all get the same value.
        by_new_id = {}
        for row_id, _org_id, _old_id, new_id in remappable:
            by_new_id.setdefault(new_id, []).append(row_id)
        for new_id, row_ids in by_new_id.items():
            placeholders = ",".join(["%s"] * len(row_ids))
            cur.execute(
                f"UPDATE permits_to_work SET permit_type_id = %s WHERE id IN ({placeholders})",
                [new_id] + row_ids,
            )
        conn.commit()
        print(f"Remapped permits_to_work.permit_type_id on {len(remappable)} rows.")
        grand_total += len(remappable)

    print(f"\nRepaired {grand_total} mismatched references "
          f"({len(unmappable)} permit_type_id rows left unrepaired — no same-org name match).")
    print("Backup table: _reference_mismatch_backup")


if __name__ == "__main__":
    main()
