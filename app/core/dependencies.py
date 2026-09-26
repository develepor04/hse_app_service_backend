from typing import Optional
from fastapi import Depends, HTTPException, Request, Query, status
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.user import User
from app.services.auth_service import decode_access_token


class PaginationParams:
    """Reusable pagination dependency injected into any list endpoint."""

    def __init__(
        self,
        skip: int = Query(default=0, ge=0, description="Records to skip"),
        limit: int = Query(default=100, ge=1, le=1000, description="Max records to return"),
    ) -> None:
        self.skip = skip
        self.limit = limit


class CurrentUser:
    """Decoded JWT payload for the authenticated user."""

    def __init__(self, user_id: int, username: str, email: str, role: str, org_id: Optional[int]):
        self.user_id = user_id
        self.username = username
        self.email = email
        self.role = role
        self.org_id = org_id


def get_current_user(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    """FastAPI dependency — validates JWT and returns the current user with org_id."""
    import logging
    logger = logging.getLogger("app.core.middleware")
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    token = auth_header.removeprefix("Bearer ").strip()
    payload = decode_access_token(token)
    if payload is None:
        logger.info("Token decoding failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    token_user_id = int(payload.get("sub", 0))
    token_email = payload.get("email", "")
    token_org_id = payload.get("org_id")

    user = None
    if token_user_id:
        user = db.query(User).filter(User.id == token_user_id).first()
    if user is None and token_email:
        user = db.query(User).filter(User.email == token_email).first()

    if user is not None and not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account has been deactivated",
        )

    org_id = user.organisation_id if user and user.organisation_id is not None else token_org_id
    role = payload.get("role", "")
    if org_id is not None:
        try:
            org_id = int(org_id)
        except (TypeError, ValueError):
            org_id = None
    if org_id is None and role.lower() != "superadmin":
        # Normal tenant users without completed organisation setup must not see
        # global/seed rows. Most tenant controllers interpret None as unscoped,
        # so use an impossible id to produce empty tenant-scoped results.
        org_id = -1

    return CurrentUser(
        user_id=token_user_id,
        username=user.username if user else payload.get("username", ""),
        email=user.email if user else token_email,
        role=role,
        org_id=org_id,
    )


def require_valid_org(current_user: CurrentUser) -> int:
    """Guard for write endpoints: refuse to write data for a user whose
    organisation could not be resolved, rather than silently stamping the
    -1 sentinel (see get_current_user) onto a new row. A record saved with
    that sentinel can never match a real organisation_id again, so it is
    written successfully and then invisible everywhere, forever.
    """
    if current_user.org_id is None or current_user.org_id < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your account is not linked to an organisation yet. Contact your administrator before submitting reports.",
        )
    return current_user.org_id


def require_superadmin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Gate for platform-wide (cross-organisation) administration routes.

    Unlike org-scoped tenant data, these routes act on every organisation at
    once (user accounts, subscriptions, platform notifications) — they must
    never be reachable by an org-scoped user, let alone an unauthenticated
    caller.
    """
    if (current_user.role or "").strip().lower() != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="SuperAdmin access required",
        )
    return current_user


def get_current_user_optional(
    request: Request, db: Session = Depends(get_db)
) -> Optional[CurrentUser]:
    """Same as get_current_user but returns None instead of raising.

    Lets an endpoint attribute actions to the JWT user when one is present while
    still serving callers that identify themselves via X-User-* headers.
    """
    try:
        return get_current_user(request, db)
    except HTTPException:
        return None
