from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey
from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    username         = Column(String(100), nullable=False, unique=True)
    full_name        = Column(String(255), nullable=True)
    email            = Column(String(255), nullable=False, unique=True)
    password_hash    = Column(String(255), nullable=False)
    app_role_id      = Column(Integer, ForeignKey("app_roles.id"), nullable=False)
    employee_id      = Column(Integer, ForeignKey("employees.id"), nullable=True)
    organisation_id  = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    is_active        = Column(Boolean, nullable=False, default=True)
    last_login       = Column(DateTime, nullable=True)
