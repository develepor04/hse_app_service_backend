from typing import List, Dict
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.services.notification import NotificationService
from app.schemas.notification import NotificationOut, NotificationCreate, UnreadCountOut

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _svc(db: Session = Depends(get_db)) -> NotificationService:
    return NotificationService(db)


@router.get("/", response_model=List[NotificationOut])
def list_notifications(
    skip: int = 0,
    limit: int = Query(50, le=1000),
    svc: NotificationService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.list_for_user(org_id=current_user.org_id, user_id=current_user.user_id, skip=skip, limit=limit)


@router.get("/unread-count", response_model=UnreadCountOut)
def unread_count(
    svc: NotificationService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    count = svc.get_unread_count(org_id=current_user.org_id, user_id=current_user.user_id)
    return {"count": count}


@router.post("/{id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_read(
    id: int,
    svc: NotificationService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    svc.mark_read(notification_id=id, org_id=current_user.org_id, user_id=current_user.user_id)


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
def mark_all_read(
    svc: NotificationService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    svc.mark_all_read(org_id=current_user.org_id, user_id=current_user.user_id)


@router.post("/", response_model=NotificationOut, status_code=status.HTTP_201_CREATED)
def create_notification(
    payload: NotificationCreate,
    svc: NotificationService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.create(payload, org_id=current_user.org_id)
