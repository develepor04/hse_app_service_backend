"""
Seeds default system users (superadmin + admin).
Passwords are bcrypt-hashed; change them immediately after first login.
"""

import hashlib
import os

from seeds.base import BaseSeeder
from app.models.user import User
from app.models.app_role import AppRole


def _hash_password(plain: str) -> str:
    try:
        from passlib.context import CryptContext
        ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
        return ctx.hash(plain)
    except ImportError:
        # Fallback if passlib is not installed: SHA-256 + salt (dev only)
        salt = os.urandom(16).hex()
        digest = hashlib.sha256(f"{salt}{plain}".encode()).hexdigest()
        return f"sha256:{salt}:{digest}"


class UsersSeeder(BaseSeeder):
    model      = User
    unique_key = "username"

    # ── default credentials ───────────────────────────────────────────────────
    # Change these before deploying to any shared environment.
    _DEFAULTS = [
        {
            "username":    "superadmin",
            "email":       "superadmin@hse-intel.com",
            "plain_pass":  "SuperAdmin@123",
            "role_name":   "superadmin",
            "is_active":   True,
        },
        {
            "username":    "admin",
            "email":       "admin@hse-intel.com",
            "plain_pass":  "Admin@123",
            "role_name":   "admin",
            "is_active":   True,
        },
        {
            "username":    "safety_manager",
            "email":       "safety.manager@hse-intel.com",
            "plain_pass":  "Safety@123",
            "role_name":   "safety_manager",
            "is_active":   True,
        },
        {
            "username":    "demo_viewer",
            "email":       "viewer@hse-intel.com",
            "plain_pass":  "Viewer@123",
            "role_name":   "viewer",
            "is_active":   True,
        },
    ]

    def data(self) -> list[dict]:
        # Look up app_role ids from the already-seeded app_roles table
        role_map: dict[str, int] = {
            r.name: r.id
            for r in self._db.query(AppRole).all()
        }

        records = []
        for entry in self._DEFAULTS:
            role_id = role_map.get(entry["role_name"])
            if role_id is None:
                print(f"  WARNING: app_role '{entry['role_name']}' not found — skipping {entry['username']}")
                continue

            records.append({
                "username":      entry["username"],
                "email":         entry["email"],
                "password_hash": _hash_password(entry["plain_pass"]),
                "app_role_id":   role_id,
                "employee_id":   None,
                "is_active":     entry["is_active"],
            })

        return records
