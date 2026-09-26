"""Schemas for the deterministic gate engine."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class GateResultOut(BaseModel):
    gate_key: str
    verdict: str  # pass | amber | block
    reason: str
    details: Dict[str, Any] = {}
    hard: bool = False


class GateEvaluationOut(BaseModel):
    overall: str
    blocked_reasons: List[str] = []
    gates: List[GateResultOut] = []


class PermitGateCheck(BaseModel):
    permit_id: int
    employee_ids: Optional[List[int]] = None
    persist: bool = True


class JourneyGateCheck(BaseModel):
    journey_plan_id: int
    employee_ids: Optional[List[int]] = None
    weather: Optional[Dict[str, Any]] = None
    persist: bool = True


class GateDecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_type: str
    subject_id: Optional[int] = None
    gate_key: str
    verdict: str
    reason: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    subject_employee_id: Optional[int] = None
    evaluated_by: Optional[int] = None
    evaluated_at: Optional[datetime] = None


class OverrideCreate(BaseModel):
    """D4 — every override captures reason, context and outcome.

    This is the spec's Core Feature: the signal the learning loop trains on,
    and the record that makes a decision defensible to a regulator.
    """

    gate_decision_id: Optional[int] = None
    subject_type: Optional[str] = None
    subject_id: Optional[int] = None
    gate_key: Optional[str] = None
    decision: str = Field(..., pattern="^(accept|amend|reject)$")
    reason: str = Field(..., min_length=10)
    context: Optional[str] = None
    outcome: Optional[str] = None
    resulting_verdict: Optional[str] = None


class OverrideOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    gate_decision_id: Optional[int] = None
    subject_type: Optional[str] = None
    subject_id: Optional[int] = None
    gate_key: Optional[str] = None
    decision: str
    reason: str
    context: Optional[str] = None
    outcome: Optional[str] = None
    original_verdict: Optional[str] = None
    resulting_verdict: Optional[str] = None
    overridden_by: Optional[int] = None
    overridden_by_role: Optional[str] = None
    overridden_at: Optional[datetime] = None
