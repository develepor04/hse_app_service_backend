import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pymysql
import bcrypt

from app.config.settings import get_settings

password = os.environ.get("SUPERADMIN_PASSWORD")
if not password:
    raise SystemExit(
        "SUPERADMIN_PASSWORD is not set. Run:\n"
        "  SUPERADMIN_PASSWORD='<a strong password>' python create_superadmin.py"
    )

settings = get_settings()
hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

conn = pymysql.connect(
    host=settings.db_host,
    port=settings.db_port,
    user=settings.db_user,
    password=settings.db_password,
    database=settings.db_name,
)
cur = conn.cursor()

# Ensure superadmin app_role exists
cur.execute("SELECT id FROM app_roles WHERE name='superadmin'")
row = cur.fetchone()
if row:
    role_id = row[0]
    print(f"superadmin role already exists (id={role_id})")
else:
    cur.execute(
        "INSERT INTO app_roles (name, label, description, level) VALUES (%s, %s, %s, %s)",
        ("superadmin", "Super Administrator", "Full platform access", 100),
    )
    conn.commit()
    role_id = cur.lastrowid
    print(f"Created superadmin role (id={role_id})")

# Create or update superadmin user
cur.execute("SELECT id FROM users WHERE username='superadmin'")
if cur.fetchone():
    cur.execute(
        "UPDATE users SET password_hash=%s, app_role_id=%s, is_active=1 WHERE username='superadmin'",
        (hashed, role_id),
    )
    conn.commit()
    print("Updated existing superadmin user password")
else:
    cur.execute(
        "INSERT INTO users (username, email, password_hash, app_role_id, is_active) VALUES (%s, %s, %s, %s, %s)",
        ("superadmin", "superadmin@hse.local", hashed, role_id, 1),
    )
    conn.commit()
    print(f"Created superadmin user (id={cur.lastrowid})")

cur.close()
conn.close()
print("Done.")
