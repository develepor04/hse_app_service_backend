from __future__ import annotations
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel
from app.schemas.base import TimestampMixin


class TrainingVideoBase(BaseModel):
    title: str
    description: Optional[str] = None
    video_url: str
    target_roles: List[str]


class TrainingVideoCreate(TrainingVideoBase):
    pass


class TrainingVideoUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    video_url: Optional[str] = None
    target_roles: Optional[List[str]] = None


class TrainingVideoResponse(TrainingVideoBase, TimestampMixin):
    id: int

    model_config = {"from_attributes": True}


class TrainingVideoCommentCreate(BaseModel):
    comment_text: str


class TrainingVideoCommentResponse(BaseModel):
    id: int
    training_video_id: int
    comment_text: str
    author_id: Optional[int] = None
    author_name: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
