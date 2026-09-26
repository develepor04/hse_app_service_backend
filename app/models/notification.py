from sqlalchemy import Column, String, Text, Integer, DateTime, Enum, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base


class Notification(Base):
    __tablename__ = "notifications"

    organisation_id   = Column(Integer, ForeignKey("organisation.id", ondelete="CASCADE"), nullable=True, index=True)
    title             = Column(String(255), nullable=False)
    message           = Column(Text, nullable=False)
    type              = Column(Enum("info","success","warning","maintenance","announcement", name="notif_type"), nullable=False, default="info")
    target_type       = Column(Enum("all","specific", name="notif_target"), nullable=False, default="all")
    target_invite_id  = Column(Integer, ForeignKey("organisation_invite.id", ondelete="SET NULL"), nullable=True)
    # Addressed to one employee (migration 061). NULL means org-wide, which is
    # what every notification was before — including CAPA assignments, which
    # named a person in the message body and then went to everybody.
    target_employee_id = Column(Integer, nullable=True)
    category          = Column(String(40), nullable=True)
    subject_ref       = Column(String(40), nullable=True)
    status            = Column(Enum("draft","sent","failed", name="notif_status"), nullable=False, default="sent")
    email_sent_count  = Column(Integer, nullable=False, default=0)
    sent_at           = Column(DateTime, nullable=True)

    reads             = relationship("NotificationRead", back_populates="notification", cascade="all, delete-orphan")
