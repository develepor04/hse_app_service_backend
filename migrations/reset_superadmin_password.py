"""Reset superadmin password to a value supplied via SUPERADMIN_PASSWORD."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pymysql
import bcrypt

from app.config.settings import get_settings

new_password = os.environ.get("SUPERADMIN_PASSWORD")
if not new_password:
    raise SystemExit(
        "SUPERADMIN_PASSWORD is not set. Run:\n"
        "  SUPERADMIN_PASSWORD='<a strong password>' python reset_superadmin_password.py"
    )
hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()

settings = get_settings()
DB = dict(
    host=settings.db_host,
    port=settings.db_port,
    user=settings.db_user,
    password=settings.db_password,
    database=settings.db_name,
    charset="utf8mb4",
)
conn = pymysql.connect(**DB)
cur = conn.cursor()
cur.execute("UPDATE users SET password_hash = %s WHERE email = 'superadmin@hse.local'", (hashed,))
conn.commit()
print(f"Updated {cur.rowcount} row(s)")
print(f"Super Admin login:")
print(f"  Email: superadmin@hse.local")
print(f"  Password: {new_password}")
cur.close()
conn.close()
