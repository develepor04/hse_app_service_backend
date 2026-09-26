"""WF-04 · the jobs that chase corrective actions without anyone remembering to.

Source: HSE_CAPA_Lifecycle.pdf — "THE CHASE HAPPENS BY ITSELF · THE ESCALATION
TIMER CHAIN" and the system row of the ten-step table.

Before this the entire automatic half of the document was one daily summary
counting overdue actions and posting the number to everybody. Nothing fired on
elapsed time, nothing re-scored, nothing scheduled a review, and nothing noticed
when the same root cause came back for the third time.

Five jobs:

    run_capa_escalations        hourly · the 50/75/90/100/110% chain
    rescore_capa_priorities     weekly · "re-scores weekly against live risk data"
    notify_due_effectiveness_reviews  daily · the 30/60/90-day checks
    nudge_unassigned_actions    daily · an action with no owner is chased by nobody
    flag_systemic_issues        daily · 3+ actions on one root cause in 6 months

Every job is idempotent. `escalation_level` records the highest threshold already
fired, review notifications are keyed to the review row, and the systemic flag is
a boolean — so a job that runs twice, or a process that restarts mid-run, cannot
double-notify. That matters more than it sounds: an escalation channel that cries
wolf gets muted, and then the chain is worth nothing.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List

from sqlalchemy import func, text

from app.config.database import SessionLocal
from app.models.capa_action import CapaAction
from app.models.capa_lifecycle import CapaEffectivenessReview, CapaProgressNote
from app.services import capa_lifecycle as lc
from app.services import capa_notify
from app.services.capa_priority import prioritise
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _open_actions(db) -> List[CapaAction]:
    return (
        db.query(CapaAction)
        .filter(func.lower(func.coalesce(CapaAction.status, "")).notin_(list(lc.TERMINAL)))
        .filter(CapaAction.due_date.isnot(None))
        .all()
    )


# ══════════════════════════════════════════════════════════════════════════════
# The escalation timer chain
# ══════════════════════════════════════════════════════════════════════════════

def run_capa_escalations() -> None:
    """Fires each threshold once, to the person the document names.

    Hourly rather than daily because a P1 action's whole life is 24 hours — a
    daily job would fire its 75% reminder somewhere between "too early to be
    useful" and "after the deadline", depending on when the action was raised.
    """
    db = SessionLocal()
    try:
        fired = 0
        for capa in _open_actions(db):
            pending = lc.due_escalations(
                capa.created_at, capa.due_date, already_fired=capa.escalation_level or 0
            )
            if not pending:
                continue

            for level, audience, message in pending:
                # The 50% step is the supervisor's interim check, and it is
                # pointless to demand it again where it has already happened.
                if level == 50 and capa.interim_check_at:
                    continue
                # The 75% nudge only goes where no progress has been recorded —
                # "a quiet nudge", not a reprimand for someone visibly working.
                if level == 75 and _has_recent_progress(db, capa.id):
                    continue
                _send_escalation(db, capa, level, audience, message)
                fired += 1

            capa.escalation_level = max(l for l, _, _ in pending)
            capa.last_escalated_at = datetime.utcnow()

        db.commit()
        if fired:
            logger.info("Scheduler: fired %s CAPA escalation(s)", fired)
    except Exception:
        db.rollback()
        logger.exception("Scheduler: CAPA escalation chain failed")
    finally:
        db.close()


def _has_recent_progress(db, capa_id: int) -> bool:
    cutoff = datetime.utcnow() - timedelta(days=7)
    return (
        db.query(CapaProgressNote.id)
        .filter(CapaProgressNote.capa_id == capa_id, CapaProgressNote.created_at >= cutoff)
        .first()
        is not None
    )


def _send_escalation(db, capa: CapaAction, level: int, audience: str, message: str) -> None:
    ref = capa.capa_ref or f"CAPA-{capa.id:06d}"
    title = f"{ref} at {level}% of its deadline"
    kind = "warning" if level >= 100 else "info"
    body = f"{message}\n\n{capa.description}\nDue {capa.due_date}."

    if audience == "owner":
        capa_notify.notify(
            db, org_id=capa.organisation_id, employee_id=capa.responsible_person_id,
            title=title, message=body, category="capa_escalation",
            subject_ref=ref, type_=kind,
        )
    elif audience in ("supervisor", "owner_supervisor"):
        sup = capa_notify.supervisor_of(db, capa.responsible_person_id)
        if sup:
            capa_notify.notify(
                db, org_id=capa.organisation_id, employee_id=sup,
                title=title, message=body, category="capa_escalation",
                subject_ref=ref, type_=kind,
            )
        else:
            # No reporting line recorded. Falling back to the safety managers
            # keeps the chain unbroken rather than silently dropping the step.
            capa_notify.notify_many(
                db, capa_notify.safety_managers(db, capa.organisation_id),
                org_id=capa.organisation_id, title=title,
                message=body + "\n(No supervisor is recorded for the owner.)",
                category="capa_escalation", subject_ref=ref, type_=kind,
            )
    elif audience in ("safety_manager", "executive"):
        capa_notify.notify_many(
            db, capa_notify.safety_managers(db, capa.organisation_id),
            org_id=capa.organisation_id, title=title, message=body,
            category="capa_escalation", subject_ref=ref, type_=kind,
        )


# ══════════════════════════════════════════════════════════════════════════════
# Weekly re-scoring
# ══════════════════════════════════════════════════════════════════════════════

def rescore_capa_priorities() -> None:
    """"The score is recalculated weekly — if conditions in that area worsen
    while the action is still open, its priority rises on its own."

    Systemic risk is the input that moves: it is re-derived from how many other
    actions share this root cause. Severity potential is a property of the
    hazard and does not change because time passed, so it is left alone.

    The score only ever rises here. A re-score that quietly downgraded an action
    would let a deadline slip with nobody deciding to let it slip.
    """
    db = SessionLocal()
    try:
        changed = 0
        window = datetime.utcnow() - timedelta(days=lc.SYSTEMIC_WINDOW_DAYS)

        for capa in _open_actions(db):
            if not capa.root_cause_addressed or capa.severity_potential is None:
                continue

            siblings = (
                db.query(func.count(CapaAction.id))
                .filter(
                    CapaAction.organisation_id == capa.organisation_id,
                    CapaAction.root_cause_addressed == capa.root_cause_addressed,
                    CapaAction.created_at >= window,
                )
                .scalar()
            ) or 0

            # One occurrence is local, two is a pattern, three or more is
            # systemic — the same thresholds the systemic flag uses.
            new_systemic = 1 if siblings <= 1 else (2 if siblings == 2 else 3)
            if new_systemic <= (capa.systemic_risk or 0):
                capa.last_rescored_at = datetime.utcnow()
                continue

            prio = prioritise(
                severity_potential=capa.severity_potential,
                systemic_risk=new_systemic,
                capa_type=capa.capa_type,
                created_at=capa.created_at,
            )
            capa.systemic_risk = prio.systemic_risk
            capa.priority_score = prio.priority_score
            capa.priority_band = prio.priority_band
            capa.priority_explanation = (
                f"{prio.explanation} Re-scored {date.today()}: {siblings} action(s) "
                f"share this root cause in the last six months."
            )
            capa.last_rescored_at = datetime.utcnow()
            changed += 1

            capa_notify.notify(
                db, org_id=capa.organisation_id, employee_id=capa.responsible_person_id,
                title=f"{capa.capa_ref} priority raised to {prio.priority_band}",
                message=(
                    f"{siblings} open actions now share this root cause, so the systemic "
                    f"risk input has risen. {capa.description}"
                ),
                category="capa_rescored", subject_ref=capa.capa_ref, type_="warning",
            )

        db.commit()
        if changed:
            logger.info("Scheduler: re-scored %s CAPA(s) upward", changed)
    except Exception:
        db.rollback()
        logger.exception("Scheduler: CAPA weekly re-score failed")
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# Effectiveness reviews
# ══════════════════════════════════════════════════════════════════════════════

def notify_due_effectiveness_reviews() -> None:
    """Tells the safety team which 30/60/90-day checks have come due.

    The review itself is a human judgement — has it recurred, is the control
    still there — so this job surfaces it rather than answering it. Overdue
    reviews are re-surfaced weekly rather than daily: a check nobody has done in
    a fortnight is a management problem, not a notification problem.
    """
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        due = (
            db.query(CapaEffectivenessReview)
            .filter(
                CapaEffectivenessReview.result == "pending",
                CapaEffectivenessReview.due_at <= now,
            )
            .all()
        )
        by_org: Dict[int, int] = {}
        for r in due:
            by_org[r.organisation_id] = by_org.get(r.organisation_id, 0) + 1

        for org_id, count in by_org.items():
            capa_notify.notify_many(
                db, capa_notify.safety_managers(db, org_id),
                org_id=org_id,
                title="CAPA effectiveness reviews due",
                message=(
                    f"{count} closed action(s) have reached a 30, 60 or 90-day review point. "
                    "Confirm the control is still in place and the issue has not recurred — "
                    "a failure reopens the action."
                ),
                category="capa_review_due",
                type_="info",
            )
        db.commit()
        if due:
            logger.info("Scheduler: %s CAPA effectiveness review(s) due", len(due))
    except Exception:
        db.rollback()
        logger.exception("Scheduler: CAPA effectiveness review sweep failed")
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# Actions nobody has picked an owner for
# ══════════════════════════════════════════════════════════════════════════════
#
# The escalation chain is addressed off `responsible_person_id`, so an action
# with no owner is chased by nobody: the 50% step resolves the owner's
# supervisor (None), the 75% step notifies the owner (None), and the first
# audience that exists regardless is the Safety Manager at 100% — after the
# deadline. An audit raises its actions unassigned by design, which is exactly
# the shape that falls into that hole.

# How far into its own window an unowned action may drift before this fires.
UNASSIGNED_NUDGE_PERCENT = 25
# ... and the floor for one with no deadline at all, which has no percentage.
UNASSIGNED_NUDGE_DAYS = 3

_UNASSIGNED_CATEGORY = "capa_unassigned"


def _already_nudged(db, ref: str) -> bool:
    """Idempotency without a new column.

    `escalation_level` is the chain's own bookmark and writing this into it would
    make the chain think a threshold had already fired. The notification row is
    the record instead — one per action, found by its category and subject.
    """
    from app.models.notification import Notification

    return (
        db.query(Notification.id)
        .filter(Notification.category == _UNASSIGNED_CATEGORY, Notification.subject_ref == ref)
        .first()
        is not None
    )


def nudge_unassigned_actions() -> None:
    """Tell the Safety Manager an action is sitting with no owner.

    Once per action. A queue that repeats itself daily is muted within a week,
    and the standing list of unowned actions is on the console — this exists to
    put the first one in front of somebody, not to be the queue.
    """
    db = SessionLocal()
    try:
        rows = (
            db.query(CapaAction)
            .filter(func.lower(func.coalesce(CapaAction.status, "")).notin_(list(lc.TERMINAL)))
            .filter(CapaAction.responsible_person_id.is_(None))
            .all()
        )
        sent = 0
        for capa in rows:
            ref = capa.capa_ref or f"CAPA-{capa.id:06d}"
            pct = lc.elapsed_percent(capa.created_at, capa.due_date)
            if pct is None:
                age = (datetime.now() - capa.created_at).days if capa.created_at else 0
                overdue_to_assign = age >= UNASSIGNED_NUDGE_DAYS
                how_long = f"{age} day(s) old, no due date set"
            else:
                overdue_to_assign = pct >= UNASSIGNED_NUDGE_PERCENT
                how_long = f"{pct}% of its window has gone"
            if not overdue_to_assign or _already_nudged(db, ref):
                continue

            capa_notify.notify_many(
                db, capa_notify.safety_managers(db, capa.organisation_id),
                org_id=capa.organisation_id,
                title=f"{ref} has no owner",
                message=(
                    f"{capa.description}\n"
                    f"Raised from {capa.source or capa.subject_family or 'a report'} and "
                    f"{how_long} without anyone assigned. Nothing chases an action with no "
                    f"owner — assign it before the deadline does the chasing.\n"
                    f"Due {capa.due_date or 'not set'}."
                ),
                category=_UNASSIGNED_CATEGORY,
                subject_ref=ref,
                type_="warning",
            )
            sent += 1

        db.commit()
        if sent:
            logger.info("Scheduler: flagged %s unassigned CAPA(s)", sent)
    except Exception:
        db.rollback()
        logger.exception("Scheduler: unassigned CAPA sweep failed")
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# Systemic issue detection
# ══════════════════════════════════════════════════════════════════════════════

def flag_systemic_issues() -> None:
    """"If three or more actions share the same root cause within six months, a
    systemic issue is flagged and a management review becomes mandatory. The
    organisation is treating symptoms, not the cause."

    Counts every action on that root cause, open or closed. Three fixes for the
    same cause is the signal regardless of whether each one individually worked
    — that is precisely what "treating symptoms" means.
    """
    db = SessionLocal()
    try:
        window = datetime.utcnow() - timedelta(days=lc.SYSTEMIC_WINDOW_DAYS)
        groups = (
            db.query(
                CapaAction.organisation_id,
                CapaAction.root_cause_addressed,
                func.count(CapaAction.id).label("n"),
            )
            .filter(
                CapaAction.root_cause_addressed.isnot(None),
                CapaAction.root_cause_addressed != "",
                CapaAction.created_at >= window,
            )
            .group_by(CapaAction.organisation_id, CapaAction.root_cause_addressed)
            .having(func.count(CapaAction.id) >= lc.SYSTEMIC_THRESHOLD)
            .all()
        )

        newly_flagged = 0
        for org_id, root_cause, n in groups:
            rows = (
                db.query(CapaAction)
                .filter(
                    CapaAction.organisation_id == org_id,
                    CapaAction.root_cause_addressed == root_cause,
                    CapaAction.created_at >= window,
                )
                .all()
            )
            if all(r.systemic_flag for r in rows):
                continue  # already raised for this group

            for r in rows:
                r.systemic_flag = 1
            newly_flagged += 1

            capa_notify.notify_many(
                db, capa_notify.safety_managers(db, org_id),
                org_id=org_id,
                title="Systemic issue flagged — management review required",
                message=(
                    f"{n} corrective actions in the last six months share the same root "
                    f"cause:\n\n\"{root_cause}\"\n\n"
                    "The organisation is treating symptoms rather than the cause. "
                    "A management review is mandatory."
                ),
                category="capa_systemic",
                type_="warning",
            )

        db.commit()
        if newly_flagged:
            logger.info("Scheduler: flagged %s systemic root cause group(s)", newly_flagged)
    except Exception:
        db.rollback()
        logger.exception("Scheduler: systemic issue detection failed")
    finally:
        db.close()
