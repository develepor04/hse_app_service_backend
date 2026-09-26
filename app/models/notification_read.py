from sqlalchemy import Column, Integer, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import relationship
from app.models.base import Base


class NotificationRead(Base):
    __tablename__ = "notification_reads"

    __table_args__ = (
        UniqueConstraint("notification_id", "user_id", name="uq_notif_user"),
    )

    notification_id = Column(Integer, ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id         = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    read_at         = Column(DateTime, server_default=func.now(), nullable=False)

    notification    = relationship("Notification", back_populates="reads")
