"""
BaseSeeder — every seeder extends this (SRP + OCP).
Subclasses only implement `data()` and `model`; upsert logic lives here once.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Type
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger(__name__)


class BaseSeeder(ABC):
    model: Type          # set by each concrete seeder

    def __init__(self, db: Session) -> None:
        self._db = db

    @abstractmethod
    def data(self) -> list[dict]:
        """Return the list of records to seed."""

    # ── unique key used to detect existing rows ───────────────────────────────
    @property
    def unique_key(self) -> str:
        return "id"

    def run(self) -> None:
        records = self.data()
        created = updated = skipped = 0

        for record in records:
            key_val = record.get(self.unique_key)
            existing = (
                self._db.query(self.model)
                .filter(getattr(self.model, self.unique_key) == key_val)
                .first()
                if key_val is not None
                else None
            )

            if existing is None:
                self._db.add(self.model(**record))
                created += 1
            else:
                # Upsert: update fields that differ
                changed = False
                for k, v in record.items():
                    if getattr(existing, k, None) != v:
                        setattr(existing, k, v)
                        changed = True
                if changed:
                    updated += 1
                else:
                    skipped += 1

        self._db.flush()
        logger.info(
            "[%s] created=%d  updated=%d  skipped=%d",
            self.__class__.__name__, created, updated, skipped,
        )
        print(
            f"  [{self.__class__.__name__}]  "
            f"created={created}  updated={updated}  skipped={skipped}"
        )
