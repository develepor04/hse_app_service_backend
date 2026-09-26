"""WF-05 step 01 · the system builds the calendar.

"Audits are not booked by hand. The system generates the annual programme from
each site's risk band." Until now that sentence had nothing behind it — audits
were created one at a time through POST /audits, which is booking by hand.

    Looks up risk band to frequency, generates the year's events, notifies
    auditees, sets a reminder 14 days out.

Three properties this has to hold, none of which are obvious:

  · **Idempotent.** Regenerating a year must not double-book it. The generator
    counts what already exists in each window and only fills the gap, so running
    it twice in March produces the same calendar as running it once.

  · **It never touches an audit that has started.** Regeneration after a band
    change reschedules the future, not the past. An audit already walked is a
    record, not a plan.

  · **Unauthorised programmes generate nothing.** The Safety Manager authorises
    the programme for their site; generating a year of work nobody signed off is
    exactly the "booked by hand" problem wearing a different hat.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.audit import Audit, AuditProgramme
from app.services import audit_programme, audit_templates, capa_notify
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Audits are scheduled this far into the working day, so a generated calendar
# entry has a sensible time rather than midnight.
START_HOUR = 9
# How long an audit is expected to take, which is what the 110% overdue rule
# measures against.
INSPECTION_WINDOW_DAYS = 1
AUDIT_WINDOW_DAYS = 2


@dataclass
class GenerationResult:
    site_id: Optional[int]
    site_name: Optional[str]
    risk_band: str
    inspections_created: int = 0
    audits_created: int = 0
    skipped_existing: int = 0
    reason: Optional[str] = None
    created_ids: List[int] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.inspections_created + self.audits_created


def _windows(start: date, end: date, every_days: int) -> List[date]:
    """The dates in [start, end) spaced `every_days` apart."""
    out: List[date] = []
    cursor = start
    while cursor < end:
        out.append(cursor)
        cursor = cursor + timedelta(days=every_days)
    return out


def _existing_in_window(
    db: Session, org_id: Optional[int], site_id: Optional[int],
    scope: str, window_start: date, window_end: date,
) -> int:
    """How many audits of this scope are already booked in this window.

    Counts everything, including audits created by hand — a site that already has
    a quarterly audit booked does not need the generator to add a second one just
    because a person entered it rather than the system.
    """
    return (
        db.query(Audit.id)
        .filter(
            Audit.organisation_id == org_id,
            Audit.site_id == site_id,
            Audit.audit_scope == scope,
            Audit.scheduled_date >= datetime.combine(window_start, datetime.min.time()),
            Audit.scheduled_date < datetime.combine(window_end, datetime.min.time()),
        )
        .count()
    )


def _create(
    db: Session, row: AuditProgramme, *, scope: str, when: date,
    window_days: int, user_id: Optional[int], checklist_type: Optional[str],
) -> Audit:
    scheduled = datetime.combine(when, datetime.min.time()) + timedelta(hours=START_HOUR)
    template, items = audit_templates.resolve(db, row.organisation_id, checklist_type)

    label = "Inspection" if scope == "inspection" else "Audit"
    a = Audit(
        organisation_id=row.organisation_id,
        title=f"{when.strftime('%b %Y')} {checklist_type or 'Site'} {label} — {row.site_name or 'Site'}",
        checklist_type=checklist_type,
        site_id=row.site_id,
        site_name=row.site_name,
        scheduled_date=scheduled,
        due_date=scheduled + timedelta(days=window_days),
        status="scheduled",
        priority="High" if row.risk_band in ("critical", "high") else "Med",
        progress=0,
        trigger_type="scheduled_programme",
        audit_scope=scope,
        risk_band=row.risk_band,
        site_score=row.site_score,
        generated_by_programme=True,
        template_id=template.id if template else None,
    )
    db.add(a)
    db.flush()
    a.audit_ref = f"AUD-{a.id:06d}"

    _seed_items(db, a, items)
    return a


def _seed_items(db: Session, audit: Audit, items: List[dict]) -> None:
    """Write the checklist rows, and keep the legacy JSON blob in step."""
    import json

    from app.models.audit import AuditChecklistItem

    for n, s in enumerate(items, start=1):
        db.add(AuditChecklistItem(
            organisation_id=audit.organisation_id,
            audit_id=audit.id,
            seq=n,
            section=s.get("section") or "General",
            title=(s.get("title") or "Checklist item")[:255],
            question=s.get("question"),
            clause=s.get("clause"),
            is_critical=bool(s.get("is_critical")),
        ))

    audit.findings_json = json.dumps([
        {"id": n, "title": s.get("title"), "question": s.get("question"),
         "section": s.get("section"), "response": None, "remarks": "",
         "photo_attached": False, "critical": bool(s.get("is_critical"))}
        for n, s in enumerate(items, start=1)
    ])


def generate_for_site(
    db: Session,
    row: AuditProgramme,
    *,
    year: Optional[int] = None,
    from_date: Optional[date] = None,
    user_id: Optional[int] = None,
    checklist_type: Optional[str] = None,
    require_authorisation: bool = True,
    commit: bool = True,
) -> GenerationResult:
    """Generate one site's year from its band."""
    rule = audit_programme.rule_for(row.risk_band)
    result = GenerationResult(
        site_id=row.site_id, site_name=row.site_name, risk_band=row.risk_band,
    )

    if require_authorisation and not row.authorised_at:
        result.reason = "The programme for this site has not been authorised"
        return result

    today = from_date or date.today()
    year = year or today.year
    end = date(year + 1, 1, 1)

    # The slots are a fixed grid anchored to 1 January, and past ones are
    # skipped rather than moving the grid to start at today.
    #
    # Anchoring on today is what this used to do, and it made the calendar
    # depend on the day the button was pressed. Quarterly from 21 August books
    # 21 Aug and 19 Nov; the same press four days later books 25 Aug and 23 Nov,
    # and because the duplicate check looks forward from each slot it cannot see
    # the 21 Aug booking sitting four days behind it. So it books again. Pressing
    # generate on Monday and again on Friday left the site with two "Nov 2026
    # Site Inspection" entries four days apart — which is exactly what happened
    # to org 4.
    #
    # A calendar is a schedule, not "ninety days from whenever somebody clicked".
    # With the grid fixed, the same year generates the same dates no matter when
    # or how often it is run, which is what made the idempotence claim true.
    grid_start = date(year, 1, 1)

    # Inspections and full audits run on different cadences, and the frequency
    # table gives both — a critical site is a monthly inspection AND a quarterly
    # full audit, not one or the other.
    for scope, every, window in (
        ("inspection", rule.inspection_days, INSPECTION_WINDOW_DAYS),
        ("full_audit", rule.audit_days, AUDIT_WINDOW_DAYS),
    ):
        for when in _windows(grid_start, end, every):
            # A slot whose whole period has already passed is history, not
            # something to book. Slots still running are kept: the duplicate
            # check below decides whether they already hold an event.
            if when + timedelta(days=every) <= today:
                continue
            window_end = when + timedelta(days=every)
            if _existing_in_window(db, row.organisation_id, row.site_id, scope, when, window_end):
                result.skipped_existing += 1
                continue
            a = _create(
                db, row, scope=scope, when=when, window_days=window,
                user_id=user_id, checklist_type=checklist_type,
            )
            result.created_ids.append(a.id)
            if scope == "inspection":
                result.inspections_created += 1
            else:
                result.audits_created += 1

    row.programme_year = year
    row.generated_at = datetime.utcnow()
    row.generated_count = (row.generated_count or 0) + result.total

    if result.total:
        logger.info(
            "Programme generated %s event(s) for site %s (%s band): %s inspections, %s audits",
            result.total, row.site_id, row.risk_band,
            result.inspections_created, result.audits_created,
        )

    if commit:
        db.commit()
    return result


def generate_for_org(
    db: Session,
    org_id: Optional[int],
    *,
    year: Optional[int] = None,
    user_id: Optional[int] = None,
    require_authorisation: bool = True,
) -> List[GenerationResult]:
    """Generate the whole organisation's year, site by site."""
    rows = (
        db.query(AuditProgramme)
        .filter(AuditProgramme.organisation_id == org_id)
        .all()
    )
    if not rows:
        rows = audit_programme.refresh_org(db, org_id)

    results = [
        generate_for_site(
            db, r, year=year, user_id=user_id,
            require_authorisation=require_authorisation, commit=False,
        )
        for r in rows
    ]
    db.commit()

    total = sum(r.total for r in results)
    if total:
        capa_notify.notify_many(
            db, capa_notify.safety_managers(db, org_id),
            org_id=org_id,
            title=f"Audit programme generated — {total} event(s)",
            message=(
                f"The {year or date.today().year} audit calendar has been generated from each "
                "site's risk band. Assign an auditor to each — the audit cannot progress until "
                "someone independent of the area is named."
            ),
            category="audit_programme",
        )
        db.commit()
    return results


# ══════════════════════════════════════════════════════════════════════════════
# The 14-day reminder
# ══════════════════════════════════════════════════════════════════════════════

REMINDER_DAYS = 14


def send_due_reminders(db: Session, org_id: Optional[int] = None) -> int:
    """"Sets a reminder 14 days out."

    Stamped once per audit. A reminder that re-sends on every sweep teaches
    people to ignore the channel, which is worse than no reminder at all.
    """
    now = datetime.utcnow()
    horizon = now + timedelta(days=REMINDER_DAYS)

    q = db.query(Audit).filter(
        Audit.reminder_sent_at.is_(None),
        Audit.scheduled_date.isnot(None),
        Audit.scheduled_date <= horizon,
        Audit.scheduled_date >= now,
        Audit.status.in_(("scheduled", "planned", "draft")),
    )
    if org_id is not None:
        q = q.filter(Audit.organisation_id == org_id)

    sent = 0
    for a in q.all():
        recipients = []
        if a.auditee_manager_id:
            recipients.append(a.auditee_manager_id)
        if not recipients:
            recipients = capa_notify.safety_managers(db, a.organisation_id)

        days = (a.scheduled_date - now).days
        capa_notify.notify_many(
            db, recipients,
            org_id=a.organisation_id,
            title=f"Audit in {days} day(s) — {a.site_name or 'your area'}",
            message=(
                f"{a.audit_ref}: {a.title} is scheduled for "
                f"{a.scheduled_date.strftime('%d %b %Y')}. "
                + (
                    "An auditor has been assigned. Prepare records and make your team available."
                    if a.auditor_id else
                    "No auditor has been assigned yet — the audit cannot proceed without one."
                )
            ),
            category="audit_reminder",
            subject_ref=a.audit_ref,
        )
        a.reminder_sent_at = now
        sent += 1

    if sent:
        db.commit()
        logger.info("Sent %s audit reminder(s) at the %s-day mark", sent, REMINDER_DAYS)
    return sent


def run_reminder_sweep() -> None:
    """Scheduler entry point — every organisation, once a day."""
    from app.config.database import SessionLocal

    db = SessionLocal()
    try:
        send_due_reminders(db)
    except Exception:
        logger.exception("Audit reminder sweep failed")
    finally:
        db.close()
