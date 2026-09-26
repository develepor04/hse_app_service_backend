from datetime import datetime
from sqlalchemy import Column, Integer, DateTime, func
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """All ORM models inherit from this base — provides id + audit timestamps."""

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
