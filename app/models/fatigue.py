"""WF-06 · Fatigue declaration (AI-ISMS class C7).

Non-medical, privacy-safe proxies only — shift length, consecutive days, night
shifts, task intensity. The spec is explicit that this must never become a
medical or biometric record.

    F = ((Shift Hrs - 8) x 1.5) + ((Consec. Days - 5) x 2) + (Night Shifts in 7d x 3)

    <10  acceptable
    10-14 amber, supervisor acknowledges
    15-19 sign-off required before a high-risk permit
    >=20  hard block, 8 h rest, Safety Manager exception only
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, Text

from app.models.aiisms_mixin import AiIsmsMetadataMixin
from app.models.base import Base


class FatigueDeclaration(Base, AiIsmsMetadataMixin):
    __tablename__ = "fatigue_declarations"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    declared_at = Column(DateTime, nullable=True, index=True)

    shift_hours = Column(Numeric(5, 2), nullable=False, default=0)
    consecutive_days = Column(Integer, nullable=False, default=0)
    night_shifts_7d = Column(Integer, nullable=False, default=0)
    task_intensity = Column(String(20), nullable=True)

    fatigue_index = Column(Numeric(6, 2), nullable=False, default=0)
    band = Column(String(20), nullable=False, default="acceptable", index=True)

    # 10-14: supervisor acknowledges. 15-19: supervisor signs off with a note.
    supervisor_ack_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    supervisor_ack_at = Column(DateTime, nullable=True)
    supervisor_signoff_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    supervisor_signoff_at = Column(DateTime, nullable=True)
    signoff_note = Column(Text, nullable=True)

    # >=20 is a hard block. Only a Safety Manager may authorise an exception,
    # and only with a written reason.
    exception_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    exception_at = Column(DateTime, nullable=True)
    exception_reason = Column(Text, nullable=True)
