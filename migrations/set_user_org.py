import pymysql

DB = dict(host="localhost", port=3306, user="root", password="", database="hse_db", charset="utf8mb4")
conn = pymysql.connect(**DB)
cur = conn.cursor()

# Set organisation_id = 1 for the user
cur.execute(
    "UPDATE users SET organisation_id = 1 WHERE email = 'sonawanenavnath2026@gmail.com'"
)
conn.commit()
print(f"Updated {cur.rowcount} user(s) — organisation_id set to 1")

# Confirm
cur.execute("SELECT id, email, username, organisation_id FROM users WHERE email = 'sonawanenavnath2026@gmail.com'")
u = cur.fetchone()
print(f"User now: id={u[0]}, email={u[1]}, username={u[2]}, organisation_id={u[3]}")

cur.close()
conn.close()
