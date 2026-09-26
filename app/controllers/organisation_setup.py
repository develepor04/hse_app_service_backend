from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.core.rate_limit import rate_limit
from app.models.organisation import Organisation
from app.models.organisation_invite import OrganisationInvite
from app.models.user import User
from app.services.excel_import_service import import_excel, import_excel_stream
from app.utils.logger import get_logger

router = APIRouter(prefix="/organisation/setup", tags=["Organisation Setup"])
logger = get_logger(__name__)

_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


def _validate_upload(file: UploadFile, content: bytes) -> None:
    if not (file.filename and (file.filename.endswith(".xlsx") or file.filename.endswith(".xls"))):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .xlsx / .xls files are accepted",
        )
    if len(content) > _MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds the 50 MB limit",
        )


def _require_pending_invite(email: str, db: Session) -> OrganisationInvite:
    """The caller's JWT email must have a pending setup invite.

    Import must never run for an account with no matching invite — that was
    the unauthenticated-import hole (unbounded org/site/employee/... injection
    by anyone who could reach the API).
    """
    email = email.strip().lower()
    invite = (
        db.query(OrganisationInvite)
        .filter(
            OrganisationInvite.admin_email == email,
            OrganisationInvite.status == "pending",
        )
        .order_by(OrganisationInvite.id.desc())
        .first()
    )
    if not invite:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No pending organisation setup invite for this account.",
        )
    return invite


def _mark_invite_accepted(invite: OrganisationInvite, min_org_id: int, db: Session) -> None:
    email = invite.admin_email
    invite.status = "accepted"

    # Link the admin user to the org this call just imported — the org with
    # the smallest id greater than the snapshot taken before import started,
    # never just "the most recent org row" (which could belong to a different,
    # concurrently-running setup).
    org = (
        db.query(Organisation)
        .filter(Organisation.id > min_org_id)
        .order_by(Organisation.id.asc())
        .first()
    )
    if org:
        admin_user = db.query(User).filter(User.email == email).first()
        if admin_user and admin_user.organisation_id is None:
            admin_user.organisation_id = org.id
            logger.info("Linked admin %s → org_id=%s (%s)", email, org.id, org.organisation_name)

    db.commit()
    logger.info("Invite id=%s marked accepted for %s", invite.id, email)


@router.get("/check", summary="Check if an email has a pending org invite (needs setup)")
def check_setup_required(
    email: str,
    db: Session = Depends(get_db),
    _rl: None = Depends(rate_limit("setup-check", max_requests=10, window_seconds=60)),
):
    email = email.strip().lower()
    invite = (
        db.query(OrganisationInvite)
        .filter(
            OrganisationInvite.admin_email == email,
            OrganisationInvite.status == "pending",
        )
        .first()
    )
    if not invite:
        return {"needs_setup": False}

    # If the user already has an organisation_id, they completed setup already.
    # Auto-accept the stale invite so they never see the wizard again.
    user = db.query(User).filter(User.email == email).first()
    if user and user.organisation_id is not None:
        invite.status = "accepted"
        db.commit()
        logger.info("Auto-accepted stale invite for %s (org_id=%s)", email, user.organisation_id)
        return {"needs_setup": False}

    return {
        "needs_setup": True,
        "organisation_name": invite.organisation_name,
        "admin_name": invite.admin_name,
        "invite_id": invite.id,
    }


@router.post(
    "/upload-stream",
    summary="Upload Excel and stream per-sheet import progress (SSE)",
)
async def upload_excel_stream(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    content = await file.read()
    _validate_upload(file, content)
    invite = _require_pending_invite(current_user.email, db)
    min_org_id = db.query(Organisation.id).order_by(Organisation.id.desc()).limit(1).scalar() or 0
    logger.info("Streaming Excel upload: %s bytes from %s", len(content), current_user.email)

    def _stream():
        for event in import_excel_stream(content, db):
            yield event
        # After streaming completes, mark invite accepted
        _mark_invite_accepted(invite, min_org_id, db)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/upload",
    summary="Upload organisation Excel to bulk-import all data (non-streaming)",
    status_code=status.HTTP_200_OK,
)
async def upload_organisation_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    content = await file.read()
    _validate_upload(file, content)
    invite = _require_pending_invite(current_user.email, db)
    min_org_id = db.query(Organisation.id).order_by(Organisation.id.desc()).limit(1).scalar() or 0
    logger.info("Organisation Excel upload: %s bytes from %s", len(content), current_user.email)

    try:
        results = import_excel(content, db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except Exception as exc:
        logger.error("Unexpected error during Excel import: %s", exc, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unexpected import error")

    _mark_invite_accepted(invite, min_org_id, db)

    total_rows = sum(v for v in results.values() if isinstance(v, int))
    return {
        "success": True,
        "message": f"Successfully imported {total_rows:,} records across {len(results)} tables",
        "total_rows": total_rows,
        "sheets": results,
    }
