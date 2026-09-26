"""Near miss lifecycle tracking for the admin console.

`/near-miss-workflow` answers "what can I do next" for the role doing the work.
This answers "what was done, by whom, when" for the person accountable for the
whole lifecycle — the same split `/incident-workflow` and `/incident-trail` have.
Nothing here writes.

The router is built by `report_trail_factory`, which near misses, unsafe acts
and risk reports can all share: they carry the same `ReportWorkflowMixin`
columns, so the trail is reconstructed identically for each.
"""
from app.controllers.report_trail_factory import build_trail_router


def _list_fields(row: dict) -> dict:
    """What a near miss has and the other report families do not.

    "What could this have been" is the whole point of a near miss, so it sits on
    the list row as well as the detail — an admin scanning the queue is ranking
    by potential, not by what actually happened, which was nothing.
    """
    return {"potential_consequence": row.get("potential_consequence")}


def _record_fields(row: dict) -> dict:
    event_at = row.get("event_date_time")
    return {
        "potential_consequence": row.get("potential_consequence"),
        "underlying_cause": row.get("underlying_cause"),
        # Where and which hazard, when neither was on the register.
        "location_other": row.get("location_other"),
        "hazard_other": row.get("hazard_other"),
        # near_misses names its timestamp column event_date_time, where the other
        # families use observed_date_time or nothing at all.
        "event_date_time": event_at.isoformat() if event_at else None,
    }


router = build_trail_router(
    report_type="near_miss",
    table="near_misses",
    prefix="/near-miss-trail",
    tag="Near Miss Trail",
    noun="near miss",
    # Matches the mobile queue and the closure event, so one record is named
    # identically wherever the admin meets it.
    ref_prefix="NEA",
    extra_list_fields=_list_fields,
    extra_record_fields=_record_fields,
)
