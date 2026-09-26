import pymysql

DB = dict(host="localhost", port=3306, user="root", password="", database="hse_db", charset="utf8mb4")
conn = pymysql.connect(**DB)
cur = conn.cursor()

cur.execute("""
    SELECT u.id, u.username, u.email, u.is_active, u.organisation_id,
           a.name as role_name, a.level,
           CASE WHEN u.password_hash IS NULL OR u.password_hash = '' THEN 'NO PASSWORD' ELSE 'HAS PASSWORD' END as pw_status
    FROM users u
    LEFT JOIN app_roles a ON u.app_role_id = a.id
""")
users = cur.fetchall()
print("Users:")
for u in users:
    print(f"  id={u[0]}  username={u[1]}  email={u[2]}  active={u[3]}  org_id={u[4]}  role={u[5]}  level={u[6]}  password={u[7]}")

cur.close()
conn.close()
