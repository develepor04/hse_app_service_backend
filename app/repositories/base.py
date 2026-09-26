"""
BaseRepository — generic CRUD implementation (OCP: open for extension).
Subclasses declare  model_class = MyModel  and call __init__(db) only.
"""

from typing import Generic, TypeVar, Optional, Type, ClassVar, List, Dict
from sqlalchemy.orm import Session
from app.repositories.interface import IRepository

T = TypeVar("T")


class BaseRepository(IRepository[T], Generic[T]):
    model_class: ClassVar[Type]   # set by each concrete repository

    def __init__(self, db: Session) -> None:
        self._db = db

    # ── IRepository contract ──────────────────────────────────────────────────

    def get_all(self, skip: int = 0, limit: int = 100) -> List[T]:
        return (
            self._db.query(self.model_class)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_all_by_org(self, org_id: int, skip: int = 0, limit: int = 100) -> List[T]:
        """Return records for the organisation only."""
        return (
            self._db.query(self.model_class)
            .filter(self.model_class.organisation_id == org_id)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_by_id(self, id: int) -> Optional[T]:
        return (
            self._db.query(self.model_class)
            .filter(self.model_class.id == id)
            .first()
        )

    def get_by_id_and_org(self, id: int, org_id: int) -> Optional[T]:
        """Return a record belonging to the organisation."""
        return (
            self._db.query(self.model_class)
            .filter(
                self.model_class.id == id,
                self.model_class.organisation_id == org_id,
            )
            .first()
        )

    def create(self, data: dict) -> T:
        obj = self.model_class(**data)
        self._db.add(obj)
        self._db.flush()
        self._db.refresh(obj)
        return obj

    def update(self, id: int, data: dict) -> Optional[T]:
        obj = self.get_by_id(id)
        if obj is None:
            return None
        for key, value in data.items():
            setattr(obj, key, value)
        self._db.flush()
        self._db.refresh(obj)
        return obj

    def update_by_org(self, id: int, org_id: int, data: dict) -> Optional[T]:
        obj = self.get_by_id_and_org(id, org_id)
        if obj is None:
            return None
        for key, value in data.items():
            setattr(obj, key, value)
        self._db.flush()
        self._db.refresh(obj)
        return obj

    def delete(self, id: int) -> bool:
        obj = self.get_by_id(id)
        if obj is None:
            return False
        self._db.delete(obj)
        self._db.flush()
        return True

    def delete_by_org(self, id: int, org_id: int) -> bool:
        obj = self.get_by_id_and_org(id, org_id)
        if obj is None:
            return False
        self._db.delete(obj)
        self._db.flush()
        return True
