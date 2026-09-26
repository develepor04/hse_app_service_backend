from sqlalchemy import Column, ForeignKey, Integer, String, Text
from app.models.base import Base


class HazardCategory(Base):
    __tablename__ = "hazard_categories"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    category_name = Column(String(100), nullable=False)
    description = Column(Text)
