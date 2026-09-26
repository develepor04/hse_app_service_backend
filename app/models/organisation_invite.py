from sqlalchemy import Column, String, Enum
from app.models.base import Base


class OrganisationInvite(Base):
    __tablename__ = "organisation_invite"

    organisation_name = Column(String(255), nullable=False)
    admin_name = Column(String(255), nullable=False)
    admin_email = Column(String(255), nullable=False, index=True)
    temp_password = Column(String(255), nullable=False)
    status = Column(
        Enum("pending", "accepted", "expired", name="invite_status"),
        nullable=False,
        default="pending",
        server_default="pending",
    )
