"""Risk report lifecycle tracking for the admin console.

`/risk-workflow` answers "what can I do next" for the role doing the work.
This answers "what was done, by whom, when" for the person accountable for the
whole lifecycle — the same split `/incident-workflow` and `/incident-trail`
have, and the same one near misses got.

Reads `risk_reports` — a worker's field observation of an unsafe condition —
and deliberately NOT the `hazards` register, which is a different table with a
different status vocabulary and its own trail at `/hazard-trail`. The two are
easy to conflate and the console must not: a risk observation is one sighting,
a register entry is a standing hazard that stays open until controlled.

The router is built by `report_trail_factory`, shared with near misses and
unsafe acts, because all three carry `ReportWorkflowMixin` and so the trail is
reconstructed from identical columns. What risk reports have that the others do
not is the WF-01 scoring block — the raw L×S, the four mandatory uplifts, the
adjusted score and the band it produces — and that is what the two hooks below
add. Without them the admin sees a risk's stage but not why it was ranked where
it was, which is the whole substance of a risk report.
"""
from typing import Optional

from app.controllers.report_trail_factory import build_trail_router


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def _scoring(row: dict) -> dict:
    """The WF-01 numbers, shaped the same way in the list and the detail.

    `risk_score` is the raw likelihood × consequence and `adjusted_risk_score`
    is that plus the uplifts, capped at 25 — see `app.services.risk_scoring`.
    Both are carried because they answer different questions: the raw score is
    what the matrix on the analytics page plots, the adjusted one is what banded
    the risk and decided whether work was blocked. Showing only one would make
    a risk look mis-banded to anyone who checked the arithmetic.
    """
    raw = row.get("raw_risk_score")
    if raw is None:
        raw = row.get("risk_score")
    return {
        "risk_title": row.get("risk_title"),
        "risk_category": row.get("risk_category"),
        "likelihood": row.get("likelihood"),
        "consequence": row.get("consequence"),
        "raw_risk_score": raw,
        "adjusted_risk_score": row.get("adjusted_risk_score"),
        "uplift_total": row.get("uplift_total") or 0,
        "risk_band": row.get("risk_band"),
        "risk_colour": row.get("risk_colour"),
        "blocks_work": bool(row.get("blocks_work")),
    }


def _list_fields(row: dict) -> dict:
    return _scoring(row)


def _record_fields(row: dict) -> dict:
    """Everything the list carries, plus what only the detail pane has room for.

    The four uplift flags are itemised rather than summed because `uplift_total`
    alone cannot be checked. An admin asking why a score of 9 was banded High
    needs to see that it was the no-valid-RAMS +2 and the night-shift +1, not a
    number that has to be taken on trust.
    """
    return {
        **_scoring(row),
        "review_frequency": row.get("review_frequency"),
        "approval_route": row.get("approval_route"),
        "risk_explanation": row.get("risk_explanation"),
        "existing_controls": row.get("existing_controls"),
        "suggested_controls": row.get("suggested_controls"),
        "hazard_id": row.get("hazard_id"),
        "observed_date_time": _iso(row.get("observed_date_time")),
        "uplifts": [
            {"key": "no_valid_rams", "label": "No valid RAMS", "points": 2,
             "applied": bool(row.get("uplift_no_valid_rams"))},
            {"key": "new_worker", "label": "New worker (under 30 days)", "points": 1,
             "applied": bool(row.get("uplift_new_worker"))},
            {"key": "night_shift", "label": "Night shift (22:00–06:00)", "points": 1,
             "applied": bool(row.get("uplift_night_shift"))},
            {"key": "temporary_control", "label": "Temporary control in place", "points": 1,
             "applied": bool(row.get("uplift_temporary_control"))},
        ],
    }


router = build_trail_router(
    report_type="risk",
    table="risk_reports",
    prefix="/risk-trail",
    tag="Risk Trail",
    noun="risk report",
    # RIS, matching what the mobile queue prints and what the closure event
    # publishes. Emphatically not HAZ — that is the hazard register's stem, and
    # two families answering to one reference is how an admin ends up chasing
    # the wrong record.
    ref_prefix="RIS",
    extra_list_fields=_list_fields,
    extra_record_fields=_record_fields,
)
