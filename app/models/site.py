from sqlalchemy import Column, ForeignKey, Integer, String
from app.models.base import Base


class Site(Base):
    __tablename__ = "sites"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    site_name = Column(String(255), nullable=False)
    address = Column(String(255))
    postcode = Column(String(20))
    city = Column(String(100))
    type = Column(String(100))
    operational_status = Column(String(50))
    number_of_working_stations = Column(Integer)
    capacity = Column(Integer)
    primary_products = Column(String(255))
    hazard_classification = Column(String(50))

    # Drives Appendix A statutory reportability — see app.services.statutory_reporting.
    # Nullable on purpose: an unset jurisdiction returns "cannot determine"
    # rather than defaulting to a regulator this site may not answer to.
    jurisdiction = Column(String(8), nullable=True)  # UK | US | UAE | KSA | AU | EU
    # Sub-national authority selector: emirate (UAE), state (AU), member state (EU).
    # Without it those three still raise the obligation but cannot name the
    # specific regulator — the obligation comes back marked encoded=False.
    region = Column(String(60), nullable=True)
