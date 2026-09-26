from __future__ import annotations
from typing import Optional, Any
from datetime import date, datetime, time
from decimal import Decimal
from pydantic import BaseModel, field_validator
from app.schemas.base import TimestampMixin


class EmployeeBase(BaseModel):
    full_name: str
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    employment_type: Optional[str] = None
    employment_start_date: Optional[date] = None
    role_id: Optional[int] = None
    department_id: Optional[int] = None
    shift_pattern: Optional[str] = None
    manager_id: Optional[int] = None
    induction_date: Optional[date] = None
    active_status: Optional[str] = None


class EmployeeCreate(EmployeeBase):
    pass


#: Largest accepted photo payload. Base64 inflates by ~4/3, so this caps the
#: underlying image at roughly 1.5 MB — ample for a downscaled avatar.
MAX_PHOTO_CHARS = 2_000_000
_ALLOWED_PHOTO_PREFIXES = ("data:image/jpeg;base64,", "data:image/png;base64,")


class MyPhotoUpdate(BaseModel):
    """Profile photo as a base64 data URI, or null to clear it."""

    photo: Optional[str] = None

    @field_validator("photo")
    @classmethod
    def _check_photo(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        if not v.startswith(_ALLOWED_PHOTO_PREFIXES):
            raise ValueError("photo must be a base64 data URI of type image/jpeg or image/png")
        if len(v) > MAX_PHOTO_CHARS:
            raise ValueError("photo is too large; please choose a smaller image")
        return v


class MyProfileUpdate(BaseModel):
    """Fields a user may change on their OWN employee record.

    Deliberately excludes role_id, department_id, manager_id, employment_*,
    induction_date and active_status: those are org records, and letting a user
    set their own role_id would be privilege escalation.
    """

    date_of_birth: Optional[date] = None
    gender: Optional[str] = None

    @field_validator("gender")
    @classmethod
    def _check_gender(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        v = v.strip().upper()
        if v not in ("M", "F"):
            raise ValueError("gender must be 'M' or 'F'")
        return v


class EmployeeUpdate(BaseModel):
    full_name: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    employment_type: Optional[str] = None
    employment_start_date: Optional[date] = None
    role_id: Optional[int] = None
    department_id: Optional[int] = None
    shift_pattern: Optional[str] = None
    manager_id: Optional[int] = None
    induction_date: Optional[date] = None
    active_status: Optional[str] = None


class EmployeeResponse(EmployeeBase, TimestampMixin):
    id: int

    model_config = {"from_attributes": True}
