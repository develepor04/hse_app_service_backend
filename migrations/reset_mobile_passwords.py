"""Reset the mobile-role logins (worker/supervisor/manager/auditor) to known values.

All four roles now authenticate against the backend (see
mobile/src/services/authService.ts) so the manager's approve/close and permit steps
carry a real role/org token. manager01 is a safety_manager in org 1.
"""
import os
import bcrypt
import pymysql
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

CREDENTIALS = {
    "worker_test":     "Worker@123",
    "supervisor_test": "Supervisor@123",
    "manager_test":    "Manager@123",
    "auditor_test":    "Auditor@123",
}

DB = dict(
    host=os.getenv("DB_HOST", "localhost"),
    port=int(os.getenv("DB_PORT", 3306)),
    user=os.getenv("DB_USER", "root"),
    password=os.getenv("DB_PASSWORD", ""),
    database=os.getenv("DB_NAME", "hse_db"),
    charset="utf8mb4",
)

conn = pymysql.connect(**DB)
cur = conn.cursor()

for username, plain in CREDENTIALS.items():
    hashed = bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()
    cur.execute("UPDATE users SET password_hash = %s WHERE username = %s", (hashed, username))
    status = "updated" if cur.rowcount else "NOT FOUND"
    print(f"  {username:14} {plain:16} {status}")

conn.commit()
cur.close()
conn.close()
