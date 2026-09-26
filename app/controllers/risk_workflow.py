"""Risk report workflow: Worker → Supervisor → Manager.

Routes live under /risk-workflow and write to the `risk_reports` table — deliberately
NOT the `hazards` catalog, which the website reads as organisation-wide reference data.
"""
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.controllers.report_workflow_factory import build_workflow_router
from app.models.risk_report import RiskReport
from app.schemas.report_workflow import RiskReportCreate
from app.services.risk_scoring import score_risk


def _is_night_shift(observed_at: Optional[datetime]) -> bool:
    """WF-01 uplift 3 — night shift is 22:00-06:00.

    Derived from the observation timestamp when the client does not state it,
    so the uplift cannot be lost simply because the mobile form has no such
    checkbox. The window wraps midnight, hence the `or` rather than a range.
    """
    if observed_at is None:
        return False
    return observed_at.hour >= 22 or observed_at.hour < 6


def _category_name(db: Session, given: Optional[str], org_id: Optional[int]) -> Optional[str]:
    """`risk_category` is a name, but the form used to send a category id.

    ReportRiskScreen carried the hazard-category list hard-coded as ids 1-10 —
    organisation 1's rows — and riskService stringified the chosen id into this
    column. So a worker picking "Electrical" stored the literal "2": not a
    category name, and not even this organisation's row. Every risk report in
    the system reads back a bare digit where a category belongs.

    A digit is resolved to the category name, scoped to the caller's own
    organisation by matching the foreign row's name against theirs. Anything
    already a name is passed through untouched, which is what the fixed form
    sends and what the website has always sent.
    """
    text_value = (given or "").strip()
    if not text_value or not text_value.isdigit():
        return text_value or None
    row = db.execute(
        text("SELECT category_name, organisation_id FROM hazard_categories WHERE id = :id"),
        {"id": int(text_value)},
    ).mappings().first()
    if row is None:
        return None
    name = row["category_name"]
    if row["organisation_id"] in (None, org_id):
        return name
    # The id belonged to another tenant. The name is the part worth keeping, and
    # only if this org has a category of the same name.
    mine = db.execute(
        text(
            "SELECT category_name FROM hazard_categories "
            "WHERE category_name = :name AND organisation_id = :org LIMIT 1"
        ),
        {"name": name, "org": org_id},
    ).mappings().first()
    return mine["category_name"] if mine else None


def _build_row(payload: RiskReportCreate, data: Dict[str, Any], ctx) -> Dict[str, Any]:
    # The client may send an explicit night_shift flag. If it does not, infer it
    # from when the risk was observed.
    night_shift = data.get("night_shift")
    if night_shift is None:
        night_shift = _is_night_shift(data.get("observed_date_time"))

    result = score_risk(
        likelihood=data.get("likelihood"),
        # `risk_reports` names this column "consequence"; the WF-01 matrix calls
        # the same axis severity.
        severity=data.get("consequence"),
        raw_score=data.get("risk_score"),
        no_valid_rams=bool(data.get("no_valid_rams")),
        new_worker=bool(data.get("new_worker")),
        night_shift=bool(night_shift),
        temporary_control=bool(data.get("temporary_control")),
    )

    return {
        "risk_title": data.get("risk_title"),
        "risk_category": _category_name(ctx.db, data.get("risk_category"), ctx.org_id),
        "likelihood": data.get("likelihood"),
        "consequence": data.get("consequence"),
        # risk_score stays the raw L x S — the website and the analytics queries
        # already read it and expect an unadjusted 1-25.
        "risk_score": result.raw_score,
        "raw_risk_score": result.raw_score,
        "uplift_no_valid_rams": int(bool(data.get("no_valid_rams"))),
        "uplift_new_worker": int(bool(data.get("new_worker"))),
        "uplift_night_shift": int(bool(night_shift)),
        "uplift_temporary_control": int(bool(data.get("temporary_control"))),
        "uplift_total": result.uplift_total,
        "adjusted_risk_score": result.adjusted_score,
        "risk_band": result.band,
        "risk_colour": result.colour,
        "review_frequency": result.review_frequency,
        "approval_route": result.approval_route,
        "blocks_work": int(result.blocks_work),
        "risk_explanation": result.explanation,
        "existing_controls": data.get("existing_controls"),
        "suggested_controls": data.get("suggested_controls"),
        "hazard_id": data.get("hazard_id"),
        # Both asked by the risk form and, until now, in neither the request
        # type nor this builder — collected on the screen and dropped before
        # the network call.
        "potential_consequence": data.get("potential_consequence"),
        "underlying_cause": data.get("underlying_cause"),
        "location_other": data.get("location_other"),
        "hazard_other": data.get("hazard_other"),
    }


router = build_workflow_router(
    report_type="risk",
    model=RiskReport,
    prefix="/risk-workflow",
    tag="Risk Workflow",
    create_schema=RiskReportCreate,
    build_row=_build_row,
    detail_fields=[
        "risk_title", "risk_category", "likelihood", "consequence",
        "risk_score", "existing_controls", "suggested_controls", "hazard_id",
        # The scored outcome, not just the inputs. `risk_score` above is the raw
        # L x S; what actually decides how the risk is treated is the adjusted
        # score, the band it falls in and whether work is blocked — and that is
        # the part the reporter needs read back to them. Without these the
        # worker's own screen could show the numbers they entered but not the
        # verdict those numbers produced.
        "adjusted_risk_score", "uplift_total", "risk_band", "risk_colour",
        "blocks_work", "approval_route", "review_frequency", "risk_explanation",
        # The four uplifts individually, not just their total. "+3" tells a
        # reviewer the score moved; which three tell them why, and whether the
        # reason still holds — a night-shift uplift means something different
        # at the next review than a missing-RAMS one.
        "raw_risk_score", "uplift_no_valid_rams", "uplift_new_worker",
        "uplift_night_shift", "uplift_temporary_control",
        # Context the worker gave, previously stored and never read back.
        "potential_consequence", "underlying_cause", "location_other", "hazard_other",
    ],
    noun="risk report",
)
