"""Set full_name for users who have NULL full_name, derived from email or known names."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config.database import SessionLocal
from app.models.user import User

# Map email → correct full name (add more as needed)
NAME_MAP = {
    "sonawanenavnath2026@gmail.com": "Navnath Sonawane",
    "nmtsolutiontech@gmail.com": "NMT Solution Tech",
    "nmtsolutiontech2@gmail.com": "Navnath",
}

db = SessionLocal()
try:
    users = db.query(User).filter(User.full_name == None).all()
    print(f"Found {len(users)} users with NULL full_name")
    updated = 0
    for u in users:
        if u.email in NAME_MAP:
            u.full_name = NAME_MAP[u.email]
            print(f"  Set full_name='{u.full_name}' for {u.email}")
            updated += 1
        else:
            # Derive from username: "sonawanenavnath2026" → keep as is,
            # but at least set it so we don't keep falling back to username
            # (skip unknown users)
            print(f"  SKIP (no mapping): {u.email} / {u.username}")
    db.commit()
    print(f"\nDone — updated {updated} user(s).")
finally:
    db.close()
