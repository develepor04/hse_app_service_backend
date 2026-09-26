"""Unsafe Act workflow: Worker → Supervisor → Manager.

Routes live under /unsafe-act-workflow and write to the `unsafe_acts` table.
"""
from typing import Any, Dict

from app.controllers.report_workflow_factory import build_workflow_router
from app.models.unsafe_act import UnsafeAct
from app.schemas.report_workflow import UnsafeActReport


def _build_row(payload: UnsafeActReport, data: Dict[str, Any], ctx) -> Dict[str, Any]:
    return {
        "act_type": data.get("act_type"),
        "person_observed": data.get("person_observed"),
        "rule_violated": data.get("rule_violated"),
        "corrective_advice_given": data.get("corrective_advice_given"),
    }


router = build_workflow_router(
    report_type="unsafe_act",
    model=UnsafeAct,
    prefix="/unsafe-act-workflow",
    tag="Unsafe Act Workflow",
    create_schema=UnsafeActReport,
    build_row=_build_row,
    detail_fields=["act_type", "person_observed", "rule_violated", "corrective_advice_given"],
    noun="unsafe act",
)
