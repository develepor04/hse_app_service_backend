"""Unsafe act lifecycle tracking for the admin console.

`/unsafe-act-workflow` answers "what can I do next" for the role doing the
work. This answers "what was done, by whom, when" for the person accountable
for the whole lifecycle — the same split `/incident-workflow` and
`/incident-trail` have. Nothing here writes.

The router is built by `report_trail_factory`, the same factory near misses
and risk reports use — see near_miss_trail.py. This one was the gap: the
workflow write-side (unsafe_act_workflow.py) has existed since near miss did,
but nothing ever built the read-side trail for it, so there was nowhere on
web to see an unsafe act once submitted.
"""
from app.controllers.report_trail_factory import build_trail_router


def _list_fields(row: dict) -> dict:
    return {"act_type": row.get("act_type")}


def _record_fields(row: dict) -> dict:
    observed_at = row.get("observed_date_time")
    return {
        "act_type": row.get("act_type"),
        "person_observed": row.get("person_observed"),
        "rule_violated": row.get("rule_violated"),
        "corrective_advice_given": row.get("corrective_advice_given"),
        # unsafe_acts names its timestamp column observed_date_time, matching
        # near_miss_trail's event_date_time handling for its own column name.
        "observed_date_time": observed_at.isoformat() if observed_at else None,
    }


router = build_trail_router(
    report_type="unsafe_act",
    table="unsafe_acts",
    prefix="/unsafe-act-trail",
    tag="Unsafe Act Trail",
    noun="unsafe act",
    # Matches report_trail_factory's own docstring (NEA / UNS / RIS) and the
    # mobile queue/closure event naming, so one record reads identically
    # wherever the admin meets it.
    ref_prefix="UNS",
    extra_list_fields=_list_fields,
    extra_record_fields=_record_fields,
)
