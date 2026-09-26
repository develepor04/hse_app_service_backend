from __future__ import annotations
from typing import Literal, Optional, List
from datetime import datetime
from pydantic import BaseModel, EmailStr


class InviteOrganisationRequest(BaseModel):
    organisation_name: str
    admin_name: str
    admin_email: EmailStr


class InviteOrganisationResponse(BaseModel):
    id: int
    organisation_name: str
    admin_name: str
    admin_email: str
    status: Literal["pending", "accepted", "expired"]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InviteListResponse(BaseModel):
    total: int
    items: List[InviteOrganisationResponse]
