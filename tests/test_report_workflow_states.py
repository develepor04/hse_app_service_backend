"""Regression tests for U-011: acknowledge/escalate must validate the
record's prior workflow_status, the same way investigate/verify/close already
do — before this fix a closed or approved record could be forced back to an
earlier stage by calling acknowledge/escalate out of order.

Pure unit tests — no database, no API key, no network.

    cd backend && python3 -m pytest tests/test_report_workflow_states.py -q
"""
from dataclasses import dataclass

import pytest
from fastapi import HTTPException

from app.controllers.report_workflow_factory import (
    ACKNOWLEDGE_FROM,
    ESCALATE_FROM,
    _require_report_state,
)


@dataclass
class _Row:
    workflow_status: str


def test_acknowledge_from_reported_is_allowed():
    _require_report_state(_Row("reported"), "incident", ACKNOWLEDGE_FROM, "acknowledged")


@pytest.mark.parametrize("status", ["acknowledged", "under_investigation", "escalated", "approved", "closed"])
def test_acknowledge_rejects_every_other_status(status):
    with pytest.raises(HTTPException) as excinfo:
        _require_report_state(_Row(status), "incident", ACKNOWLEDGE_FROM, "acknowledged")
    assert excinfo.value.status_code == 409


@pytest.mark.parametrize("status", ["reported", "acknowledged", "under_investigation"])
def test_escalate_allowed_from_active_stages(status):
    _require_report_state(_Row(status), "incident", ESCALATE_FROM, "escalated")


@pytest.mark.parametrize("status", ["approved", "capa_open", "pending_verification", "closed"])
def test_escalate_rejects_closed_or_past_supervisor_stages(status):
    """The bug this closes: a closed/approved record could be forced back to
    'escalated' by calling this endpoint out of order."""
    with pytest.raises(HTTPException) as excinfo:
        _require_report_state(_Row(status), "incident", ESCALATE_FROM, "escalated")
    assert excinfo.value.status_code == 409
