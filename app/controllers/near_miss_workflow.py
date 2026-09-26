"""Near Miss workflow: Worker → Supervisor → Manager.

Routes live under /near-miss-workflow and write to the `near_misses` table.
Separate from the website's read-only /near-misss/ CRUD router, which is untouched.
"""
from typing import Any, Dict

from app.controllers.report_workflow_factory import build_workflow_router
from app.models.near_miss import NearMiss
from app.schemas.report_workflow import NearMissReport


def _build_row(payload: NearMissReport, data: Dict[str, Any], ctx) -> Dict[str, Any]:
    return {
        "potential_consequence": data.get("potential_consequence"),
        "underlying_cause": data.get("underlying_cause"),
        "hazard_id": data.get("hazard_id"),
        # Both are enum('Yes','No') in MySQL, so normalise before writing.
        "control_failure": _yes_no(data.get("control_failure")),
        "capa_escalation": _yes_no(data.get("capa_escalation")),
        # Written only when the worker chose "Other"; the matching id is unset.
        "location_other": data.get("location_other"),
        "hazard_other": data.get("hazard_other"),
        # Sent by the screen since it was written and dropped on the floor
        # until 075: the field was in neither the schema nor the table.
        "suggested_controls": data.get("preventative_suggestion"),
    }


def _yes_no(value: Any) -> str:
    return "Yes" if str(value or "").strip().lower() in ("yes", "true", "1") else "No"


router = build_workflow_router(
    report_type="near_miss",
    model=NearMiss,
    prefix="/near-miss-workflow",
    tag="Near Miss Workflow",
    create_schema=NearMissReport,
    build_row=_build_row,
    detail_fields=[
        "potential_consequence", "underlying_cause", "hazard_id",
        "control_failure", "capa_escalation",
        # Read back to the reporter on My Near Misses and to the supervisor on
        # review — a field worth collecting is worth showing.
        "location_other", "hazard_other",
        # The worker's own suggestion for preventing it next time.
        "suggested_controls",
    ],
    # near_misses names its timestamp column event_date_time
    observed_at_field="event_date_time",
    noun="near miss",
)
