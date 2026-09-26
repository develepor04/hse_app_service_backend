import pymysql

DB = dict(host="localhost", port=3306, user="root", password="", database="hse_db", charset="utf8mb4")
conn = pymysql.connect(**DB)
cur = conn.cursor()

# Show organisation table structure
cur.execute("DESCRIBE organisation")
cols = cur.fetchall()
print("organisation table columns:")
for c in cols:
    print(f"  {c[0]:30s}  {c[1]}")

# Show all orgs
cur.execute("SELECT * FROM organisation LIMIT 10")
rows = cur.fetchall()
print(f"\nRows in organisation ({len(rows)} found):")
for r in rows:
    print(f"  {r}")

# Show user
cur.execute("SELECT id, email, username, organisation_id FROM users WHERE email = 'sonawanenavnath2026@gmail.com'")
user = cur.fetchone()
if user:
    print(f"\nUser: id={user[0]}, email={user[1]}, username={user[2]}, organisation_id={user[3]}")
else:
    print("\nUser not found!")

cur.close()
conn.close()
