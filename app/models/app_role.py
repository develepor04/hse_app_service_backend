from sqlalchemy import Column, String, Text, SmallInteger
from app.models.base import Base


class AppRole(Base):
    __tablename__ = "app_roles"

    name        = Column(String(50),  nullable=False, unique=True)
    label       = Column(String(100), nullable=False)
    description = Column(Text)
    level       = Column(SmallInteger, nullable=False, default=0)
