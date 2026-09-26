"""
IRepository — abstract contract every repository must fulfil (ISP / DIP).
Concrete repositories extend BaseRepository[T] which implements this interface.
"""

from abc import ABC, abstractmethod
from typing import Generic, TypeVar, Optional, List

T = TypeVar("T")


class IRepository(ABC, Generic[T]):
    @abstractmethod
    def get_all(self, skip: int, limit: int) -> List[T]: ...

    @abstractmethod
    def get_by_id(self, id: int) -> Optional[T]: ...

    @abstractmethod
    def create(self, obj: T) -> T: ...

    @abstractmethod
    def update(self, id: int, obj: T) -> Optional[T]: ...

    @abstractmethod
    def delete(self, id: int) -> bool: ...

