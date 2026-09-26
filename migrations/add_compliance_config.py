"""Add compliance_config JSON column to organisation table."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    db.execute(text(
        "ALTER TABLE organisation ADD COLUMN compliance_config JSON NULL AFTER establishment_date"
    ))
    db.commit()
    print("Done — compliance_config column added to organisation table.")
except Exception as e:
    if "Duplicate column" in str(e) or "1060" in str(e):
        print("Column already exists — skipping.")
    else:
        raise
finally:
    db.close()
