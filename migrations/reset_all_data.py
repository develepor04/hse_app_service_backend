"""
Full database reset — deletes ALL data except app_roles and the superadmin user.
Safe to run multiple times.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pymysql

from app.config.settings import get_settings
from _safety import confirm_destructive

_settings = get_settings()
DB = dict(
    host=_settings.db_host,
    port=_settings.db_port,
    user=_settings.db_user,
    password=_settings.db_password,
    database=_settings.db_name,
    charset="utf8mb4",
)

# Tables to TRUNCATE completely (order matters for FK constraints)
TRUNCATE_TABLES = [
    # checklist tables
    "checklist_logs",
    "checklist_submission_items",
    "checklist_submissions",
    "checklist_templates",
    # business data
    "capa_actions",
    "near_misses",
    "incidents",
    "safety_walks",
    "permits_to_work",
    "hazards",
    "hazard_categories",
    "working_stations",
    "shift_schedule",
    "training_programs",
    "policies",
    "permit_types",
    "employees",
    "departments",
    "roles",
    "sites",
    # superadmin tables
    "subscription",
    "notification",
    "organisation_invite",
    # org & users (users handled separately below)
    "organisation",
]

confirm_destructive(_settings.db_name, "delete all data except app_roles and the superadmin user")

conn = pymysql.connect(**DB)
cur = conn.cursor()

print("Disabling foreign key checks...")
cur.execute("SET FOREIGN_KEY_CHECKS = 0")

for table in TRUNCATE_TABLES:
    try:
        cur.execute(f"TRUNCATE TABLE `{table}`")
        print(f"  TRUNCATED  {table}")
    except Exception as e:
        print(f"  SKIP       {table}  ({e})")

# Delete all users EXCEPT superadmin
cur.execute("DELETE FROM users WHERE email != 'superadmin@hse.local'")
print(f"  DELETED    {cur.rowcount} user(s)  (superadmin@hse.local kept)")

cur.execute("SET FOREIGN_KEY_CHECKS = 1")
print("Re-enabled foreign key checks.")

conn.commit()

# Confirm what's left
cur.execute("SELECT id, username, email, app_role_id FROM users")
rows = cur.fetchall()
print("\nUsers remaining:")
for r in rows:
    print(f"  id={r[0]}  username={r[1]}  email={r[2]}  role_id={r[3]}")

cur.execute("SELECT COUNT(*) FROM organisation")
print(f"Organisations: {cur.fetchone()[0]}")

cur.execute("SELECT COUNT(*) FROM incidents")
print(f"Incidents: {cur.fetchone()[0]}")

cur.execute("SELECT COUNT(*) FROM employees")
print(f"Employees: {cur.fetchone()[0]}")

cur.close()
conn.close()
print("\nDatabase reset complete. Ready for fresh testing.")
