"""Request and response shapes for WF-01 Flow B."""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class AssessmentCreate(BaseModel):
    """Step 01 SCOPE. The supervisor names the activity and where it happens."""

    activity: str = Field(..., min_length=1)
    task_description: Optional[str] = None
    site_id: Optional[int] = None
    location_station_id: Optional[int] = None

    # The circumstances, which the uplifts read. Declared at scope time because
    # they describe the job rather than any one hazard found in it.
    no_valid_rams: bool = False
    new_worker: bool = False
    night_shift: bool = False
    temporary_control: bool = False


class CategoryAnswer(BaseModel):
    """Step 02-03. Answering one of the ten.

    `hazard_present` "No" is a complete answer and needs nothing else — most
    categories on most jobs are a No. "Yes" is what requires a likelihood and a
    severity, because a hazard nobody scored cannot drive the assessment.
    """

    hazard_present: str = Field(..., description="Yes | No")
    description: Optional[str] = None
    likelihood: Optional[str] = None
    severity: Optional[str] = None


class CategoryControl(BaseModel):
    """Steps 06-07. The control chosen and who owns it."""

    control_hierarchy: str = Field(..., description="eliminate | substitute | engineering | administrative | ppe")
    control_description: Optional[str] = None
    control_owner_id: Optional[int] = None
    control_due_date: Optional[date] = None
    # Step 08's inputs: what the hazard scores once this control is in place.
    residual_likelihood: Optional[str] = None
    residual_severity: Optional[str] = None


class AssessmentApprove(BaseModel):
    approved: bool = True
    notes: Optional[str] = None


class CategoryOut(BaseModel):
    id: int
    category_key: str
    category_name: str
    hazard_present: Optional[str] = None
    description: Optional[str] = None
    likelihood: Optional[str] = None
    severity: Optional[str] = None
    inherent_score: Optional[int] = None
    control_hierarchy: Optional[str] = None
    control_description: Optional[str] = None
    control_owner_id: Optional[int] = None
    control_due_date: Optional[date] = None
    residual_likelihood: Optional[str] = None
    residual_severity: Optional[str] = None
    residual_score: Optional[int] = None
    hazard_id: Optional[int] = None

    model_config = {"from_attributes": True}


class AssessmentOut(BaseModel):
    id: int
    reference: str
    activity: str
    task_description: Optional[str] = None
    site_id: Optional[int] = None
    location_station_id: Optional[int] = None
    status: Optional[str] = None

    step: Optional[int] = None
    step_label: Optional[str] = None
    total_steps: int = 10
    outstanding_categories: List[str] = []

    uplift_total: int = 0
    inherent_score: Optional[int] = None
    adjusted_score: Optional[int] = None
    band: Optional[str] = None

    residual_score: Optional[int] = None
    residual_band: Optional[str] = None
    blocks_work: bool = False
    approval_route: Optional[str] = None
    approved_by: Optional[int] = None
    approved_at: Optional[datetime] = None

    review_frequency: Optional[str] = None
    review_due_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None

    categories: List[CategoryOut] = []

    model_config = {"from_attributes": True}
