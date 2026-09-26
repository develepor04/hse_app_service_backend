from typing import Optional
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.user import User


def resolve_employee_id(db: Session, user_id: int) -> Optional[int]:
    """CurrentUser only carries the login account id; audit rows join on employees."""
    return db.query(User.employee_id).filter(User.id == user_id).scalar()


def record_audit(
    db: Session,
    organisation_id: Optional[int],
    employee_id: Optional[int],
    action: str,
    module: str,
    record_id: Optional[str] = None,
    previous_value: Optional[str] = None,
    new_value: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> None:
    """Append one audit row. Caller owns the transaction — this only adds
    to the session, it does not commit (so it composes with the caller's
    existing commit for the mutating action it's logging)."""
    db.add(AuditLog(
        organisation_id=organisation_id,
        employee_id=employee_id,
        action=action,
        module=module,
        record_id=str(record_id) if record_id is not None else None,
        previous_value=previous_value,
        new_value=new_value,
        ip_address=ip_address,
    ))
