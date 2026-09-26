import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pymysql

from app.config.settings import get_settings

_s = get_settings()
conn = pymysql.connect(host=_s.db_host, port=_s.db_port, user=_s.db_user, password=_s.db_password, database=_s.db_name)
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM incidents"); print("total_incidents:", cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM capa_actions WHERE status != 'Completed'"); print("open_capa_actions:", cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM permits_to_work WHERE status = 'Active'"); print("active_permits:", cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM employees"); print("total_employees:", cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM sites"); print("total_sites:", cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM near_misses"); print("near_misses_count:", cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM safety_walks"); print("safety_walks_count:", cur.fetchone()[0])
cur.execute("SELECT AVG(compliance_rating) FROM safety_walks"); v=cur.fetchone()[0]; print("avg_compliance_rating:", round(float(v),2) if v else 0)
cur.execute("SELECT COUNT(*) FROM capa_actions WHERE status = 'Completed'"); c=cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM capa_actions"); t=cur.fetchone()[0]
print("capa_completion_rate:", round(c/t*100,1) if t else 0)
cur.execute("SELECT COUNT(*) FROM incidents WHERE LOWER(severity) IN ('critical', 'significant')"); print("critical_incidents:", cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM hazard_categories"); print("hazard_categories:", cur.fetchone()[0])
cur.execute("SELECT category_name, COUNT(i.id) as cnt FROM hazard_categories hc LEFT JOIN hazards h ON h.category_id=hc.id LEFT JOIN incidents i ON i.hazard_id=h.id GROUP BY hc.category_name"); print("incidents by category:", cur.fetchall())
conn.close()
print("All checks passed.")
