"""The closure cascade — what "Every Closure Improves the System" actually means.

Source: HSE_Workflow_Engine_Slide.pptx — "Closing an event updates risk,
training, inspections and the AI model automatically."

Four handlers, one per thing the slide names. Each is small, independent and
idempotent, and each records what it did so the cascade can be read back rather
than inferred from side effects scattered across four tables.

They subscribe to the closure of ANY event family, not just incidents. A closed
near miss teaches the same lessons as a closed incident — that is the whole
point of one engine.

Every handler is deterministic. None of them invokes a model: "updates the AI
model" is honoured by writing the closure into the lessons corpus that grounds
retrieval, which is the only learning signal this platform actually has. See
`feed_learning_corpus` for why that is stated plainly rather than dressed up.
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.events.bus import HandlerResult, subscribe
from app.services.events.catalogue import (
    HAZARD_CLOSED, INCIDENT_CLOSED, NEAR_MISS_CLOSED, UNSAFE_ACT_CLOSED,
)

logger = logging.getLogger(__name__)

ANY_CLOSURE = (INCIDENT_CLOSED, NEAR_MISS_CLOSED, UNSAFE_ACT_CLOSED, HAZARD_CLOSED)

# Root-cause categories that mean a person lacked the knowledge or skill, as
# opposed to a control failing. Only these raise a competence gap — raising one
# for a guard that fell off would train the wrong problem.
_TRAINING_ROOT_CAUSES = (
    "training", "competence", "competency", "human error", "human factors",
    "knowledge", "skill", "supervision", "instruction", "behaviour", "behavior",
)


# ══════════════════════════════════════════════════════════════════════════════
# 1 · RISK — re-open the linked hazard for review
#
# WF-01 step 9: "RA automatically re-opened when a linked incident is created."
# Closing an event is the moment we know what actually failed, so the hazard
# that event was linked to can no longer be assumed correctly assessed.
# ══════════════════════════════════════════════════════════════════════════════

@subscribe(*ANY_CLOSURE)
def reopen_linked_hazard(db: Session, envelope: Dict[str, Any], payload: Dict[str, Any]) -> HandlerResult:
    hazard_id = payload.get("hazard_id")
    if not hazard_id:
        return HandlerResult("no linked hazard", changed=False)

    row = db.execute(
        text("SELECT register_status FROM hazards WHERE id = :h AND organisation_id = :org"),
        {"h": hazard_id, "org": envelope.get("organisation_id")},
    ).mappings().first()
    if not row:
        return HandlerResult(f"hazard {hazard_id} not found", changed=False)

    if (row["register_status"] or "").lower() == "under_review":
        return HandlerResult(f"hazard {hazard_id} already under review", changed=False)

    db.execute(
        text(
            "UPDATE hazards SET register_status = 'under_review', reviewed_at = NULL "
            " WHERE id = :h AND organisation_id = :org"
        ),
        {"h": hazard_id, "org": envelope.get("organisation_id")},
    )
    db.commit()
    return HandlerResult(f"hazard {hazard_id} flagged under_review")


# ══════════════════════════════════════════════════════════════════════════════
# 2 · TRAINING — raise a competence gap when the root cause was a person, not a
# control. Safety-critical when the closed event was a P1/P2 or a HIPO.
# ══════════════════════════════════════════════════════════════════════════════

@subscribe(*ANY_CLOSURE)
def raise_competence_gap(db: Session, envelope: Dict[str, Any], payload: Dict[str, Any]) -> HandlerResult:
    category = (payload.get("root_cause_category") or "").lower()
    root_cause = (payload.get("root_cause") or "").lower()
    if not any(k in category or k in root_cause for k in _TRAINING_ROOT_CAUSES):
        return HandlerResult("root cause is not training-related", changed=False)

    employee_id = payload.get("involved_employee_id") or payload.get("reported_by")
    if not employee_id:
        return HandlerResult("no employee to attach a gap to", changed=False)

    requirement = f"Refresher from {payload.get('reference') or envelope['event_type']}"

    # Idempotent beyond the delivery key: two different closures for the same
    # person and the same requirement should not stack duplicate open gaps.
    existing = db.execute(
        text(
            "SELECT id FROM competence_gaps "
            " WHERE organisation_id = :org AND employee_id = :emp "
            "   AND requirement_name = :req AND resolved_at IS NULL"
        ),
        {"org": envelope.get("organisation_id"), "emp": employee_id, "req": requirement},
    ).scalar()
    if existing:
        return HandlerResult(f"gap {existing} already open", changed=False)

    safety_critical = 1 if (
        payload.get("priority") in ("P1", "P2") or payload.get("is_hipo")
    ) else 0

    db.execute(
        text(
            "INSERT INTO competence_gaps "
            " (organisation_id, employee_id, requirement_name, gap_type, "
            "  is_safety_critical, detected_at, source_system, created_at, updated_at) "
            " VALUES (:org, :emp, :req, 'refresher_required', :crit, :now, "
            "         'closure_cascade', :now, :now)"
        ),
        {
            "org": envelope.get("organisation_id"), "emp": employee_id,
            "req": requirement, "crit": safety_critical, "now": datetime.utcnow(),
        },
    )
    db.commit()
    return HandlerResult(
        f"competence gap raised for employee {employee_id}"
        + (" (safety-critical)" if safety_critical else "")
    )


# ══════════════════════════════════════════════════════════════════════════════
# 3 · INSPECTIONS — schedule a follow-up walk at the station where it happened.
#
# Timing follows the assessed priority: a P1/P2 closure earns a check within a
# week, a P5 within a quarter. Verifying a fix a month after a fatality would be
# theatre.
# ══════════════════════════════════════════════════════════════════════════════

_FOLLOW_UP_DAYS = {"P1": 7, "P2": 7, "P3": 30, "P4": 60, "P5": 90}

# An event closed without ever being classified is not low risk — it is unknown
# risk. Defaulting it to the P5 window (90 days) meant the events we understood
# least got checked last, which is backwards. 30 days matches P3: soon enough to
# catch a real problem, not so soon it floods the inspection schedule.
_UNCLASSIFIED_FOLLOW_UP_DAYS = 30


@subscribe(*ANY_CLOSURE)
def schedule_follow_up_inspection(db: Session, envelope: Dict[str, Any], payload: Dict[str, Any]) -> HandlerResult:
    station_id = payload.get("location_station_id")
    if not station_id:
        return HandlerResult("no station to inspect", changed=False)

    priority = payload.get("priority")
    days = _FOLLOW_UP_DAYS.get(priority or "", _UNCLASSIFIED_FOLLOW_UP_DAYS)
    due = datetime.utcnow() + timedelta(days=days)

    already = db.execute(
        text(
            "SELECT id FROM safety_walks "
            " WHERE organisation_id = :org AND location_station_id = :st "
            "   AND inspection_type = 'Closure Follow-Up' "
            "   AND inspection_date_time BETWEEN :now AND :due"
        ),
        {"org": envelope.get("organisation_id"), "st": station_id,
         "now": datetime.utcnow(), "due": due},
    ).scalar()
    if already:
        return HandlerResult(f"follow-up walk {already} already scheduled", changed=False)

    db.execute(
        text(
            "INSERT INTO safety_walks "
            " (organisation_id, inspection_date_time, location_station_id, "
            "  inspection_type, follow_up_required, created_at, updated_at) "
            " VALUES (:org, :due, :st, 'Closure Follow-Up', 'Yes', :now, :now)"
        ),
        {"org": envelope.get("organisation_id"), "due": due, "st": station_id,
         "now": datetime.utcnow()},
    )
    db.commit()
    label = priority or "unclassified"
    return HandlerResult(
        f"follow-up inspection scheduled at station {station_id} in {days} days ({label})"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 4 · THE "AI MODEL"
#
# The slide says closure updates the AI model. Nothing here retrains anything —
# this platform has no trainable model, and claiming otherwise would be the same
# category of fiction as the AI Draft button.
#
# What closure genuinely improves is the grounded corpus the assistant retrieves
# from: the lesson, the root cause and the outcome become searchable context for
# the next similar event. That is a real feedback loop, and it is the honest
# version of the claim.
# ══════════════════════════════════════════════════════════════════════════════

@subscribe(*ANY_CLOSURE)
def feed_learning_corpus(db: Session, envelope: Dict[str, Any], payload: Dict[str, Any]) -> HandlerResult:
    lesson = (payload.get("lessons_learned") or "").strip()
    if not lesson:
        return HandlerResult("no lesson recorded at closure", changed=False)

    # Notifications are the only broadcast channel that exists today, so the
    # lesson is published there and stays queryable by title prefix. When a
    # vector store lands (L4), this handler is where the embedding write goes.
    title = f"Lesson learned · {payload.get('reference') or envelope['event_type']}"
    already = db.execute(
        text("SELECT id FROM notifications WHERE organisation_id = :org AND title = :t"),
        {"org": envelope.get("organisation_id"), "t": title},
    ).scalar()
    if already:
        return HandlerResult("lesson already published", changed=False)

    body = lesson
    if payload.get("root_cause"):
        body = f"Root cause: {payload['root_cause']}\n\n{lesson}"

    db.execute(
        text(
            "INSERT INTO notifications "
            " (organisation_id, title, message, type, target_type, status, sent_at, created_at, updated_at) "
            " VALUES (:org, :t, :m, 'announcement', 'all', 'sent', :now, :now, :now)"
        ),
        {"org": envelope.get("organisation_id"), "t": title, "m": body, "now": datetime.utcnow()},
    )
    db.commit()
    return HandlerResult("lesson published to the learning corpus")
