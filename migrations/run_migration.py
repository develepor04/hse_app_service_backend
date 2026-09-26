"""
Safe migration script: adds organisation_id to all entity tables.
Checks information_schema before altering — safe to run multiple times.
"""
import os
import sys
import pymysql
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

DB = dict(
    host=os.getenv("DB_HOST", "localhost"),
    port=int(os.getenv("DB_PORT", 3306)),
    user=os.getenv("DB_USER", "root"),
    password=os.getenv("DB_PASSWORD", ""),
    database=os.getenv("DB_NAME", "hse_db"),
    charset="utf8mb4"
)

TABLES = [
    ("users",              "idx_users_org",              "fk_users_org"),
    ("employees",          "idx_employees_org",          "fk_employees_org"),
    ("sites",              "idx_sites_org",              "fk_sites_org"),
    ("incidents",          "idx_incidents_org",          "fk_incidents_org"),
    ("near_misses",        "idx_near_misses_org",        "fk_near_misses_org"),
    ("capa_actions",       "idx_capa_actions_org",       "fk_capa_actions_org"),
    ("safety_walks",       "idx_safety_walks_org",       "fk_safety_walks_org"),
    ("permits_to_work",    "idx_permits_to_work_org",    "fk_permits_to_work_org"),
    ("hazards",            "idx_hazards_org",            "fk_hazards_org"),
    ("working_stations",   "idx_working_stations_org",   "fk_working_stations_org"),
    ("policies",           "idx_policies_org",           "fk_policies_org"),
    ("training_programs",  "idx_training_programs_org",  "fk_training_programs_org"),
    ("shift_schedule",     "idx_shift_schedule_org",     "fk_shift_schedule_org"),
    ("roles",              "idx_roles_org",              "fk_roles_org"),
    ("permit_types",       "idx_permit_types_org",       "fk_permit_types_org"),
    ("departments",        "idx_departments_org",        "fk_departments_org"),
    ("hazard_categories",  "idx_hazard_categories_org",  "fk_hazard_categories_org"),
]


def column_exists(cur, table, column):
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s",
        (DB["database"], table, column),
    )
    return cur.fetchone()[0] > 0


def index_exists(cur, table, index_name):
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND INDEX_NAME = %s",
        (DB["database"], table, index_name),
    )
    return cur.fetchone()[0] > 0


def fk_exists(cur, table, fk_name):
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND CONSTRAINT_NAME = %s AND CONSTRAINT_TYPE = 'FOREIGN KEY'",
        (DB["database"], table, fk_name),
    )
    return cur.fetchone()[0] > 0


def table_exists(cur, table):
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
        (DB["database"], table),
    )
    return cur.fetchone()[0] > 0


def run():
    conn = pymysql.connect(**DB)
    cur = conn.cursor()
    errors = []

    for table, idx_name, fk_name in TABLES:
        if not table_exists(cur, table):
            print(f"  SKIP  {table} (table does not exist)")
            continue

        # 1. Add column
        if column_exists(cur, table, "organisation_id"):
            print(f"  OK    {table}.organisation_id already exists")
        else:
            try:
                cur.execute(f"ALTER TABLE `{table}` ADD COLUMN organisation_id INT NULL")
                conn.commit()
                print(f"  ADDED {table}.organisation_id")
            except Exception as e:
                errors.append(f"{table}.organisation_id: {e}")
                print(f"  ERROR {table}.organisation_id: {e}")
                conn.rollback()
                continue

        # 2. Add index
        if index_exists(cur, table, idx_name):
            print(f"  OK    index {idx_name} already exists")
        else:
            try:
                cur.execute(f"ALTER TABLE `{table}` ADD INDEX `{idx_name}` (organisation_id)")
                conn.commit()
                print(f"  ADDED index {idx_name}")
            except Exception as e:
                errors.append(f"index {idx_name}: {e}")
                print(f"  ERROR index {idx_name}: {e}")
                conn.rollback()

        # 3. Add foreign key
        if fk_exists(cur, table, fk_name):
            print(f"  OK    FK {fk_name} already exists")
        else:
            try:
                cur.execute(
                    f"ALTER TABLE `{table}` ADD CONSTRAINT `{fk_name}` "
                    f"FOREIGN KEY (organisation_id) REFERENCES organisation(id) ON DELETE SET NULL"
                )
                conn.commit()
                print(f"  ADDED FK {fk_name}")
            except Exception as e:
                errors.append(f"FK {fk_name}: {e}")
                print(f"  ERROR FK {fk_name}: {e}")
                conn.rollback()

    cur.close()
    conn.close()

    if errors:
        print(f"\nFinished with {len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("\nMigration complete — all tables updated successfully.")


if __name__ == "__main__":
    run()
