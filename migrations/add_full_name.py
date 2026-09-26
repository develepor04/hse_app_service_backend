"""Add full_name column to users table."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pymysql

from app.config.settings import get_settings

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

cur.execute("""
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'users' AND COLUMN_NAME = 'full_name'
""", (settings.db_name,))
if cur.fetchone()[0] == 0:
    cur.execute("ALTER TABLE users ADD COLUMN full_name VARCHAR(255) NULL AFTER username")
    print("Added full_name column to users table")
else:
    print("full_name already exists, skipping")

conn.commit()
cur.close()
conn.close()
print("Done.")
