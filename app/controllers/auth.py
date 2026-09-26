from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.models.user import User
from app.models.app_role import AppRole
from app.schemas.auth import DeleteAccountRequest, LoginRequest, TokenData, TokenResponse
from app.services.audit_log import record_audit, resolve_employee_id
from app.services.auth_service import verify_password, create_access_token, decode_access_token

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate with username or email + password and return a JWT."""
    # Look up user by username OR email
    user = (
        db.query(User)
        .filter(
            (User.username == payload.username) | (User.email == payload.username)
        )
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive",
        )

    # Fetch the role
    app_role = db.query(AppRole).filter(AppRole.id == user.app_role_id).first()
    if not app_role:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User role not found",
        )

    token_payload = {
        "sub": str(user.id),
        "username": user.username,
        "full_name": user.full_name,
        "email": user.email,
        "role": app_role.name,
        "role_level": app_role.level,
        "org_id": user.organisation_id,
    }

    access_token = create_access_token(token_payload)
    from datetime import timedelta
    refresh_token = create_access_token(token_payload, expires_delta=timedelta(days=7))

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=TokenData(
            user_id=user.id,
            username=user.username,
            full_name=user.full_name,
            email=user.email,
            role=app_role.name,
            role_level=app_role.level,
        ),
    )


@router.get("/me")
def get_me(request: Request):
    """Return current user info from JWT in Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    token = auth_header.removeprefix("Bearer ").strip()
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    return {
        "user_id": int(payload.get("sub", 0)),
        "username": payload.get("username"),
        "email": payload.get("email"),
        "role": payload.get("role"),
        "role_level": payload.get("role_level"),
    }


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT, summary="Self: permanently delete my own account")
def delete_my_account(
    payload: DeleteAccountRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Self-service account deletion — requires re-entering the password.
    Mirrors org_users.remove_user's admin-block, but here the actor is the
    account holder themselves rather than an org admin."""
    user = db.query(User).filter(User.id == current_user.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect password")

    role = db.query(AppRole).filter(AppRole.id == user.app_role_id).first()
    if role and role.name in ("admin", "superadmin"):
        raise HTTPException(
            status_code=403,
            detail="Admin accounts cannot self-delete — ask another admin to remove this account",
        )

    record_audit(
        db, user.organisation_id, resolve_employee_id(db, user.id),
        action="delete", module="User Account", record_id=user.id,
        previous_value=user.email, new_value="self-deleted",
    )
    db.delete(user)
    db.commit()


@router.post("/employee/refresh")
def employee_refresh(payload: dict, db: Session = Depends(get_db)):
    """Refresh the access token using a refresh token."""
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Refresh token is required",
        )
    # Decode the refresh token
    token_data = decode_access_token(refresh_token)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    
    # Retrieve user
    user_id = token_data.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token payload",
        )
        
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # Fetch role
    app_role = db.query(AppRole).filter(AppRole.id == user.app_role_id).first()
    if not app_role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User role not found",
        )

    token_payload = {
        "sub": str(user.id),
        "username": user.username,
        "full_name": user.full_name,
        "email": user.email,
        "role": app_role.name,
        "role_level": app_role.level,
        "org_id": user.organisation_id,
    }
    
    new_access_token = create_access_token(token_payload)
    return {
        "access_token": new_access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }
