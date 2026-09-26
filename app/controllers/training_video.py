from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.services.training_video import TrainingVideoService
from app.schemas.training_video import (
    TrainingVideoCreate,
    TrainingVideoUpdate,
    TrainingVideoResponse,
    TrainingVideoCommentCreate,
    TrainingVideoCommentResponse,
)
from app.models.training_video import TrainingVideoComment
from app.controllers.workflow_common import require_role, employee_id_for, mobile_role_bucket, MANAGER_ROLES

router = APIRouter(prefix="/training-videos", tags=["Training Videos"])


def _svc(db: Session = Depends(get_db)) -> TrainingVideoService:
    return TrainingVideoService(db)


@router.get("/", response_model=List[TrainingVideoResponse])
def list_training_videos(
    svc: TrainingVideoService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Admin list — every training video in the org, regardless of target audience."""
    return svc.list(org_id=current_user.org_id)


@router.get("/mine", response_model=List[TrainingVideoResponse])
def list_my_training_videos(
    svc: TrainingVideoService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Mobile list — videos targeted at the caller's own role bucket."""
    bucket = mobile_role_bucket(current_user.role)
    if bucket is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Role '{current_user.role}' has no training feed")
    return svc.list_for_role(bucket, current_user.org_id)


@router.get("/{id}", response_model=TrainingVideoResponse)
def get_training_video(id: int, svc: TrainingVideoService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.get(id, org_id=current_user.org_id)


@router.post("/", response_model=TrainingVideoResponse, status_code=status.HTTP_201_CREATED)
def create_training_video(
    payload: TrainingVideoCreate,
    svc: TrainingVideoService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role(current_user.role, MANAGER_ROLES, "create training videos")
    return svc.create(payload, org_id=current_user.org_id, created_by=employee_id_for(db, current_user.user_id))


@router.put("/{id}", response_model=TrainingVideoResponse)
def update_training_video(
    id: int,
    payload: TrainingVideoUpdate,
    svc: TrainingVideoService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, MANAGER_ROLES, "edit training videos")
    return svc.update(id, payload, org_id=current_user.org_id)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_training_video(id: int, svc: TrainingVideoService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    require_role(current_user.role, MANAGER_ROLES, "delete training videos")
    svc.delete(id, org_id=current_user.org_id)


def _employee_name(db: Session, employee_id: Optional[int], org_id: Optional[int]) -> Optional[str]:
    if not employee_id:
        return None
    from sqlalchemy import text
    return db.execute(
        text("SELECT full_name FROM employees WHERE id = :id AND organisation_id = :org_id"),
        {"id": employee_id, "org_id": org_id},
    ).scalar()


@router.get("/{id}/comments", response_model=List[TrainingVideoCommentResponse])
def list_training_video_comments(
    id: int,
    svc: TrainingVideoService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    video = svc.get(id, org_id=current_user.org_id)
    rows = (
        db.query(TrainingVideoComment)
        .filter(TrainingVideoComment.training_video_id == video.id)
        .order_by(TrainingVideoComment.created_at.desc())
        .all()
    )
    return [
        TrainingVideoCommentResponse(
            id=r.id,
            training_video_id=r.training_video_id,
            comment_text=r.comment_text,
            author_id=r.author_id,
            author_name=_employee_name(db, r.author_id, current_user.org_id),
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.post("/{id}/comments", response_model=TrainingVideoCommentResponse, status_code=status.HTTP_201_CREATED)
def add_training_video_comment(
    id: int,
    payload: TrainingVideoCommentCreate,
    svc: TrainingVideoService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    video = svc.get(id, org_id=current_user.org_id)
    author_id = employee_id_for(db, current_user.user_id)
    comment = TrainingVideoComment(
        organisation_id=current_user.org_id,
        training_video_id=video.id,
        comment_text=payload.comment_text,
        author_id=author_id,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return TrainingVideoCommentResponse(
        id=comment.id,
        training_video_id=comment.training_video_id,
        comment_text=comment.comment_text,
        author_id=comment.author_id,
        author_name=_employee_name(db, author_id, current_user.org_id),
        created_at=comment.created_at,
    )
