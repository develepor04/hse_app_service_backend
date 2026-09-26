from sqlalchemy import Column, ForeignKey, Integer, String, Text
from app.models.base import Base


class TrainingVideo(Base):
    __tablename__ = "training_videos"

    organisation_id = Column(Integer, ForeignKey("organisation.id"), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    video_url = Column(String(500), nullable=False)
    target_roles = Column(Text, nullable=False)  # JSON array of worker|supervisor|manager|auditor
    created_by = Column(Integer, nullable=True)


class TrainingVideoComment(Base):
    __tablename__ = "training_video_comments"

    organisation_id = Column(Integer, nullable=True)
    training_video_id = Column(Integer, ForeignKey("training_videos.id", ondelete="CASCADE"), nullable=False, index=True)
    comment_text = Column(Text, nullable=False)
    author_id = Column(Integer, nullable=True)
