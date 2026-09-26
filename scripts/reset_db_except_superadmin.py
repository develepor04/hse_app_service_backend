# -*- coding: utf-8 -*-
"""
reset_db_except_superadmin.py
------------------------------
Deletes ALL data from the database EXCEPT:
  - app_roles  (all roles preserved)
  - users      (only superadmin-role users preserved)

Run from the /backend directory:
    python scripts/reset_db_except_superadmin.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from app.config.database import SessionLocal
from app.config.settings import get_settings
from app.models import *
from _safety import confirm_destructive


def reset():
    confirm_destructive(get_settings().db_name, "delete all data except superadmin users")
    db = SessionLocal()
    try:
        print("\n=== HSE Database Reset (keeping SuperAdmin) ===\n")

        db.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))

        tables_to_clear = [
            "validation_logs",
            "data_imports",
            "api_integrations",
            "documents",
            "notifications",
            "organisation_invite",
            "subscriptions",
            "checklist_logs",
            "checklist_submission_items",
            "checklist_submissions",
            "checklist_templates",
            "capa_actions",
            "near_misses",
            "incidents",
            "safety_walks",
            "permits_to_work",
            "shift_schedule",
            "training_programs",
            "policies",
            "hazards",
            "hazard_categories",
            "permit_types",
            "working_stations",
            "departments",
            "roles",
            "employees",
            "sites",
            "organisation",
        ]

        for table in tables_to_clear:
            db.execute(text(f"DELETE FROM `{table}`;"))
            db.execute(text(f"ALTER TABLE `{table}` AUTO_INCREMENT = 1;"))
            print(f"  [OK]  Cleared: {table}")

        db.execute(text("""
            DELETE FROM users
            WHERE app_role_id NOT IN (
                SELECT id FROM app_roles WHERE name = 'superadmin'
            );
        """))
        db.execute(text("ALTER TABLE users AUTO_INCREMENT = 1;"))
        print("  [OK]  Cleared: users  (superadmin users preserved)")

        db.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))

        db.commit()

        superadmin_users = db.execute(
            text("""
                SELECT u.username, u.email, ar.name as role
                FROM users u
                JOIN app_roles ar ON ar.id = u.app_role_id
                WHERE ar.name = 'superadmin'
            """)
        ).fetchall()

        print("\n=== Preserved SuperAdmin Users ===")
        if superadmin_users:
            for u in superadmin_users:
                print(f"  - {u.username}  ({u.email})  role={u.role}")
        else:
            print("  (none found -- app_roles table may use a different name)")

        print("\n[DONE] Reset complete. Database is clean for fresh testing.\n")

    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] During reset: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    reset()
