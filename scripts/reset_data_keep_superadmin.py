"""Wipe all tenant/business data for a fresh test cycle, keeping only:
  - the SuperAdmin user row (users.id = 1, app_role_id = 1 'superadmin')
  - app_roles (global RBAC catalog — required for role assignment on invite)
  - checklist_templates (global checklist master templates — no organisation_id,
    used across all tenants; distinct from the per-org audit_checklist_templates)
  - _migrations (the migration ledger — never touched)

Every other table in the schema is per-tenant business/demo data (every table
was checked for an organisation_id column or confirmed empty) and is emptied
via TRUNCATE so the next org onboarding starts from auto_increment 1.

A full mysqldump was taken to ../../_local_backups/ before this ever runs
(see _pre_wipe_backup.py) — this script does not create its own backup.

Usage:
    python scripts/reset_data_keep_superadmin.py            # dry run — report only
    python scripts/reset_data_keep_superadmin.py --apply    # actually wipe
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config.database import engine
from app.config.settings import get_settings
from sqlalchemy import text
from _safety import confirm_destructive

PROTECTED_TABLES = {"_migrations", "app_roles", "checklist_templates"}
SPECIAL_TABLES = {"users"}  # handled with a scoped DELETE, not TRUNCATE


def get_all_tables(conn):
    rows = conn.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE() ORDER BY table_name")
    ).fetchall()
    return [r[0] for r in rows]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually wipe data. Without this flag, only reports the plan.")
    args = parser.parse_args()

    with engine.connect() as conn:
        all_tables = get_all_tables(conn)
        to_wipe = [t for t in all_tables if t not in PROTECTED_TABLES and t not in SPECIAL_TABLES]

        print(f"Total tables: {len(all_tables)}")
        print(f"Protected (kept fully intact): {sorted(PROTECTED_TABLES)}")
        print(f"Special-cased (users — keep only id=1 superadmin): {sorted(SPECIAL_TABLES)}")
        print(f"To TRUNCATE ({len(to_wipe)} tables): {to_wipe}\n")

        if not args.apply:
            print("Dry run only. Re-run with --apply to execute.")
            return

        confirm_destructive(get_settings().db_name, "wipe all tenant/business data")

        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for t in to_wipe:
            conn.execute(text(f"TRUNCATE TABLE `{t}`"))
            print(f"  truncated {t}")

        result = conn.execute(text("DELETE FROM users WHERE id != 1"))
        print(f"  users: deleted {result.rowcount} rows, kept id=1 (superadmin)")

        conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
        conn.commit()

        print("\nDone. Verifying...")
        u = conn.execute(text("SELECT id, username, email, app_role_id FROM users")).fetchall()
        print("users remaining:", u)
        for t in ("app_roles", "checklist_templates", "_migrations"):
            c = conn.execute(text(f"SELECT COUNT(*) FROM `{t}`")).scalar()
            print(f"{t}: {c} rows (unchanged)")
        for t in ("organisation", "employees", "incidents", "sites"):
            c = conn.execute(text(f"SELECT COUNT(*) FROM `{t}`")).scalar()
            print(f"{t}: {c} rows (should be 0)")


if __name__ == "__main__":
    main()
