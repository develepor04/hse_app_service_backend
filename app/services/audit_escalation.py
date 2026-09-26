"""WF-05 · the five escalation triggers.

"Each fires on its own, without anyone needing to notice."

That sentence is the whole design constraint. None of these is a screen someone
has to open or a report someone has to run — each is raised by the transition
that creates the condition, at the moment it is created. A critical finding
notifies the executive while the auditor is still standing in front of it.

Notification failures are logged and swallowed, following capa_notify: an alert
that could not be written must never roll back the finding that triggered it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import capa_notify
from app.services.audit_scoring import (
    ALERT_THRESHOLD,
    CRITICAL,
    MAJOR_NC,
    RE_AUDIT_THRESHOLD,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Escalation:
    key: str
    label: str
    severity: str          # info | warning | critical
    detail: str
    notified: int = 0


# The scheduled date has to slip past this multiple of the audit's planned window
# before "audit not conducted" fires. 110% of the scheduled date, per the spec.
OVERDUE_FACTOR = 1.10
# Major NC: Safety Manager within 24 hours, corrective action within 7 days.
MAJOR_NC_NOTIFY_HOURS = 24
MAJOR_NC_ACTION_DAYS = 7


def _executives(db: Session, org_id: Optional[int]) -> List[int]:
    """ISMS Director and above — the people a critical finding reaches at once."""
    try:
        rows = db.execute(
            text(
                "SELECT u.employee_id FROM users u "
                "JOIN app_roles ar ON ar.id = u.app_role_id "
                "WHERE u.organisation_id = :org AND u.is_active = 1 "
                "  AND u.employee_id IS NOT NULL "
                "  AND LOWER(ar.name) IN ('director', 'isms_director', 'admin', 'superadmin')"
            ),
            {"org": org_id},
        ).scalars().all()
        return [r for r in rows if r]
    except Exception:
        logger.exception("Could not resolve executives for org %s", org_id)
        return []


def _audience(db: Session, org_id: Optional[int], include_exec: bool) -> List[int]:
    people = list(capa_notify.safety_managers(db, org_id))
    if include_exec:
        people.extend(e for e in _executives(db, org_id) if e not in people)
    return people


def _fire(
    db: Session,
    audit,
    *,
    key: str,
    label: str,
    severity: str,
    title: str,
    message: str,
    include_exec: bool = False,
) -> Escalation:
    people = _audience(db, audit.organisation_id, include_exec)
    capa_notify.notify_many(
        db,
        people,
        org_id=audit.organisation_id,
        title=title,
        message=message,
        category="audit_escalation",
        subject_ref=audit.audit_ref or f"AUD-{audit.id}",
        # `notifications.type` is an enum of info/success/warning/maintenance/
        # announcement — there is no 'error' member, and writing one truncates
        # the column and kills the transition that raised the alert. The real
        # severity travels in `category` and in the message, which is what the
        # alert screens read anyway.
        type_="warning",
    )
    logger.info("Audit %s escalation '%s' notified %s people", audit.id, key, len(people))
    return Escalation(key=key, label=label, severity=severity, detail=message, notified=len(people))


# ══════════════════════════════════════════════════════════════════════════════
# 1 · Critical finding on site
# ══════════════════════════════════════════════════════════════════════════════

def critical_finding(db: Session, audit, finding_title: str) -> Escalation:
    """Safety Manager and executive notified immediately.

    Work may be suspended before the audit even finishes, so this fires on the
    item response — not at submit, and certainly not on the report.
    """
    return _fire(
        db, audit,
        key="critical_finding",
        label="Critical finding on site",
        severity="critical",
        title=f"CRITICAL finding — {audit.site_name or 'site'} audit in progress",
        message=(
            f"'{finding_title}' was logged as an immediate danger during audit "
            f"{audit.audit_ref or audit.id} at {audit.site_name or 'the site'}. "
            "Work may be suspended before the audit finishes."
        ),
        include_exec=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 2 · Major non-conformance
# ══════════════════════════════════════════════════════════════════════════════

def major_nc(db: Session, audit, count: int) -> Escalation:
    """Safety Manager within 24 hours, corrective action within 7 days."""
    return _fire(
        db, audit,
        key="major_nc",
        label="Major non-conformance",
        severity="critical",
        title=f"{count} Major non-conformance(s) — audit {audit.audit_ref or audit.id}",
        message=(
            f"Audit {audit.audit_ref or audit.id} at {audit.site_name or 'the site'} raised "
            f"{count} Major non-conformance(s). Acknowledgement is owed within "
            f"{MAJOR_NC_NOTIFY_HOURS} hours and a corrective action must exist within "
            f"{MAJOR_NC_ACTION_DAYS} days."
        ),
    )


# ══════════════════════════════════════════════════════════════════════════════
# 3 · Regulatory finding
# ══════════════════════════════════════════════════════════════════════════════

def regulatory_finding(db: Session, audit, finding_title: str) -> Escalation:
    """Triggers the statutory notification workflow with its own legal deadline.

    The deadline is not ours to set — `statutory_reporting` owns the jurisdiction
    rules — so this raises the obligation rather than inventing a due date.
    """
    return _fire(
        db, audit,
        key="regulatory_finding",
        label="Regulatory finding",
        severity="critical",
        title=f"Regulatory breach found — {audit.site_name or 'site'}",
        message=(
            f"'{finding_title}' was classified as a regulatory breach on audit "
            f"{audit.audit_ref or audit.id}. The statutory notification workflow applies "
            "and carries its own legal deadline."
        ),
        include_exec=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 4 · Audit not conducted
# ══════════════════════════════════════════════════════════════════════════════

def overdue_cutoff(scheduled: datetime, due: Optional[datetime]) -> datetime:
    """110% of the scheduled window. A missed audit is itself a finding.

    With no due date the window is undefined, so the cutoff is the scheduled date
    itself — an audit with no deadline that has not happened is late the moment
    its date passes.
    """
    if not due or due <= scheduled:
        return scheduled
    return scheduled + (due - scheduled) * OVERDUE_FACTOR


def audit_not_conducted(db: Session, audit) -> Escalation:
    return _fire(
        db, audit,
        key="audit_not_conducted",
        label="Audit not conducted",
        severity="warning",
        title=f"Audit {audit.audit_ref or audit.id} not conducted",
        message=(
            f"The audit scheduled for {audit.site_name or 'the site'} has passed 110% of its "
            "scheduled date without being conducted. A missed audit is itself a finding."
        ),
    )


def sweep_overdue(db: Session, org_id: Optional[int]) -> List[dict]:
    """Every audit past its 110% cutoff and still not conducted.

    Read-only. The caller decides whether to notify, because this is also what
    the auditor's dashboard renders and reading a dashboard should not send mail.
    """
    from app.models.audit import Audit

    now = datetime.utcnow()
    rows = (
        db.query(Audit)
        .filter(
            Audit.organisation_id == org_id,
            Audit.status.in_(("scheduled", "planned", "draft", "overdue")),
            Audit.scheduled_date.isnot(None),
        )
        .all()
    )
    late = []
    for a in rows:
        cutoff = overdue_cutoff(a.scheduled_date, a.due_date)
        if now > cutoff:
            late.append({
                "audit_id": a.id,
                "audit_ref": a.audit_ref,
                "title": a.title,
                "site_name": a.site_name,
                "scheduled_date": a.scheduled_date,
                "cutoff": cutoff,
                "days_late": (now - cutoff).days,
            })
    return late


# ══════════════════════════════════════════════════════════════════════════════
# 5 · Persistent poor performance
# ══════════════════════════════════════════════════════════════════════════════

def persistent_poor_performance(db: Session, audit) -> Optional[Escalation]:
    """Two Major NCs at one site in 12 months, or below 65% twice running.

    Either condition means a mandatory re-audit within 30 days. Checked at report
    issue, because that is the moment this audit's own findings become part of
    the site's history.
    """
    from app.models.audit import Audit, AuditFinding

    if not audit.site_id and not audit.site_name:
        return None

    year_ago = datetime.utcnow() - timedelta(days=365)
    site_filter = (
        Audit.site_id == audit.site_id if audit.site_id else Audit.site_name == audit.site_name
    )

    major_count = (
        db.query(AuditFinding.id)
        .join(Audit, Audit.id == AuditFinding.audit_id)
        .filter(
            Audit.organisation_id == audit.organisation_id,
            site_filter,
            AuditFinding.classification.in_((MAJOR_NC, CRITICAL)),
            AuditFinding.created_at >= year_ago,
        )
        .count()
    )

    recent_scores = (
        db.query(Audit.compliance_score)
        .filter(
            Audit.organisation_id == audit.organisation_id,
            site_filter,
            Audit.compliance_score.isnot(None),
        )
        .order_by(Audit.id.desc())
        .limit(2)
        .all()
    )
    scores = [s[0] for s in recent_scores if s[0] is not None]
    twice_below = len(scores) >= 2 and all(s < RE_AUDIT_THRESHOLD for s in scores)

    if major_count < 2 and not twice_below:
        return None

    reason = (
        f"{major_count} Major NCs at this site in 12 months"
        if major_count >= 2
        else f"score below {RE_AUDIT_THRESHOLD}% on two consecutive audits"
    )
    return _fire(
        db, audit,
        key="persistent_poor_performance",
        label="Persistent poor performance",
        severity="critical",
        title=f"Mandatory re-audit — {audit.site_name or 'site'}",
        message=(
            f"{reason.capitalize()}. A re-audit is mandatory within 30 days."
        ),
        include_exec=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Run at the points where the conditions come into existence
# ══════════════════════════════════════════════════════════════════════════════

def on_classification(db: Session, audit, findings) -> List[Escalation]:
    """Fired at step 07, when the findings acquire their classifications."""
    fired: List[Escalation] = []

    majors = [f for f in findings if f.classification == MAJOR_NC]
    if majors:
        fired.append(major_nc(db, audit, len(majors)))

    for f in findings:
        if f.classification == CRITICAL:
            fired.append(regulatory_finding(db, audit, f.title))

    if audit.compliance_score is not None and audit.compliance_score < ALERT_THRESHOLD:
        fired.append(_fire(
            db, audit,
            key="score_below_threshold",
            label="Score below alert threshold",
            severity="warning",
            title=f"Audit scored {audit.compliance_score}% — below {ALERT_THRESHOLD}%",
            message=(
                f"Audit {audit.audit_ref or audit.id} at {audit.site_name or 'the site'} scored "
                f"{audit.compliance_score}%. Anything below {ALERT_THRESHOLD}% alerts the Safety Manager "
                f"automatically; below {RE_AUDIT_THRESHOLD}% twice in a row forces a re-audit."
            ),
        ))

    return fired


def reference() -> List[dict]:
    """The five triggers, shipped to the app so it states them the same way."""
    return [
        {
            "key": "critical_finding",
            "label": "Critical finding on site",
            "detail": "Safety Manager and executive notified immediately. Work may be suspended "
                      "before the audit even finishes.",
        },
        {
            "key": "major_nc",
            "label": "Major non-conformance",
            "detail": f"Safety Manager notified within {MAJOR_NC_NOTIFY_HOURS} hours. "
                      f"A corrective action must exist within {MAJOR_NC_ACTION_DAYS} days.",
        },
        {
            "key": "regulatory_finding",
            "label": "Regulatory finding",
            "detail": "Triggers the statutory notification workflow with its own legal deadline.",
        },
        {
            "key": "audit_not_conducted",
            "label": "Audit not conducted",
            "detail": "Alert to the Safety Manager at 110% of the scheduled date. "
                      "A missed audit is itself a finding.",
        },
        {
            "key": "persistent_poor_performance",
            "label": "Persistent poor performance",
            "detail": f"Two Major NCs at one site in 12 months, or below {RE_AUDIT_THRESHOLD}% twice "
                      "running — mandatory re-audit within 30 days.",
        },
    ]
