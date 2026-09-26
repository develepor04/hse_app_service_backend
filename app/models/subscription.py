from sqlalchemy import Column, String, Integer, Numeric, Date, Text, ForeignKey, Enum
from app.models.base import Base


class Subscription(Base):
    __tablename__ = "subscriptions"

    invite_id     = Column(Integer, ForeignKey("organisation_invite.id", ondelete="SET NULL"), nullable=True, index=True)
    plan_name     = Column(String(50),  nullable=False, default="standard")
    status        = Column(Enum("trial", "active", "cancelled", "expired", name="sub_status"), nullable=False, default="active")
    billing_cycle = Column(Enum("monthly", "annual", name="billing_cycle"), nullable=False, default="monthly")
    amount        = Column(Numeric(10, 2), nullable=False, default=0)
    seats         = Column(Integer, nullable=True)
    start_date    = Column(Date, nullable=True)
    end_date      = Column(Date, nullable=True)
    notes         = Column(Text, nullable=True)
