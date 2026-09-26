"""
Seed runner — executes all seeders in dependency order.

Usage (from backend/ directory):
    python seeds/run_seeds.py

Optional flags:
    --only roles          run only the RolesSeeder
    --only app_roles      run only the AppRolesSeeder
    --only users          run only the UsersSeeder
"""

import sys
import os
import logging
import argparse

# Allow importing app.* from the backend/ directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from app.config.database import SessionLocal
from app.config.logging_config import configure_logging
import app.models  # registers all ORM models with SQLAlchemy metadata

from seeds.app_roles_seeder import AppRolesSeeder
from seeds.roles_seeder      import RolesSeeder
from seeds.users_seeder      import UsersSeeder

configure_logging()
logger = logging.getLogger(__name__)

# Ordered list: (key, SeederClass)
ALL_SEEDERS = [
    ("app_roles", AppRolesSeeder),   # must run before users
    ("roles",     RolesSeeder),
    ("users",     UsersSeeder),       # depends on app_roles
]


def run(only: str | None = None) -> None:
    db: Session = SessionLocal()
    try:
        print("\n=== HSE Seed Runner ===\n")

        for key, SeederClass in ALL_SEEDERS:
            if only and key != only:
                print(f"  [skip] {SeederClass.__name__}")
                continue

            print(f"  Seeding {SeederClass.__name__} ...")
            SeederClass(db).run()

        db.commit()
        print("\n=== All seeds applied successfully ===\n")

    except Exception as exc:
        db.rollback()
        logger.exception("Seed failed: %s", exc)
        print(f"\n  ERROR: {exc}")
        sys.exit(1)

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HSE database seeder")
    parser.add_argument(
        "--only",
        choices=[k for k, _ in ALL_SEEDERS],
        default=None,
        help="Run a single seeder by key",
    )
    args = parser.parse_args()
    run(only=args.only)
