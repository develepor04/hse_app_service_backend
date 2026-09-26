"""Schemas for stage 01 RECORD drafts.

`payload` is deliberately untyped: it mirrors whichever family's submit schema
the draft will eventually be validated against, and typing it here would mean
this file had to change every time a report form gained a field. Validation
happens at submit, against the family's own schema.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class EventDraftCreate(BaseModel):
    family: str = Field(
        ...,
        description="incident | near_miss | unsafe_act | risk | hazard_register | permit | audit",
    )
    payload: Optional[Dict[str, Any]] = None


class EventDraftUpdate(BaseModel):
    payload: Optional[Dict[str, Any]] = None


class EventDraftResponse(BaseModel):
    id: int
    family: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Always stage 01. Included so a client can render the same stage bar over a
    # draft as over a submitted record.
    stage: Optional[Dict[str, Any]] = None

    model_config = {"from_attributes": True}
