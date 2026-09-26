"""WF-05 step 03 PREPARE · the auto-generated brief pack.

"The system retrieves past findings and the regulatory guidance relevant to this
audit type, pre-populates the checklist with the highest-risk items first, and
supplies the context — previous findings, open actions, current score, overdue
permits — into a standard brief pack, 7 days before."

The auditor does not build this. They read it, on the phone, offline, before they
walk out. So it is generated once and stored on the audit rather than computed on
every read: the record has to show what the auditor was actually briefed on, not
what the data happens to look like when someone opens it months later.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.audit import Audit, AuditFinding, AuditProgramme
from app.services import audit_programme
from app.services.audit_scoring import CRITICAL, MAJOR_NC, MINOR_NC
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _previous_audits(db: Session, audit: Audit, limit: int = 2) -> List[Audit]:
    """The last two audits of this site. Two, because the repeat-finding flag
    checks the last two audits — the pack and the flag must look at the same
    window or the auditor is briefed on a different history than the one the
    system judges against."""
    if not audit.site_id and not audit.site_name:
        return []
    q = db.query(Audit).filter(
        Audit.organisation_id == audit.organisation_id,
        Audit.id != audit.id,
        Audit.submitted_at.isnot(None),
    )
    q = q.filter(Audit.site_id == audit.site_id) if audit.site_id else q.filter(
        Audit.site_name == audit.site_name
    )
    return q.order_by(Audit.submitted_at.desc()).limit(limit).all()


def previous_findings(db: Session, audit: Audit) -> List[dict]:
    """Every finding from the last two audits, and whether it was closed.

    Closed ones matter as much as open ones: a finding that was signed off and
    has come back is a repeat, which the spec treats as more serious than a first
    occurrence.
    """
    prev = _previous_audits(db, audit)
    if not prev:
        return []
    rows = (
        db.query(AuditFinding)
        .filter(AuditFinding.audit_id.in_([p.id for p in prev]))
        .order_by(AuditFinding.classification.desc(), AuditFinding.id.asc())
        .all()
    )
    by_audit = {p.id: p for p in prev}
    return [
        {
            "finding_id": f.id,
            "audit_id": f.audit_id,
            "audit_ref": (by_audit.get(f.audit_id).audit_ref if by_audit.get(f.audit_id) else None),
            "audit_date": (
                by_audit[f.audit_id].submitted_at.isoformat()
                if by_audit.get(f.audit_id) and by_audit[f.audit_id].submitted_at else None
            ),
            "title": f.title,
            "section": f.section,
            "classification": f.classification,
            "status": f.status,
            "was_closed": f.status in ("closed", "verified"),
        }
        for f in rows
    ]


def open_actions(db: Session, audit: Audit) -> List[dict]:
    """Corrective actions still outstanding against this site's audits."""
    from app.models.capa_action import CapaAction

    prev_ids = [p.id for p in _previous_audits(db, audit, limit=6)]
    if not prev_ids:
        return []
    rows = (
        db.query(CapaAction)
        .filter(
            CapaAction.subject_family == "audit",
            CapaAction.subject_id.in_(prev_ids),
            CapaAction.status != "Completed",
        )
        .order_by(CapaAction.due_date.asc())
        .all()
    )
    today = datetime.utcnow().date()
    return [
        {
            "capa_id": c.id,
            "capa_ref": c.capa_ref,
            "description": c.description,
            "due_date": c.due_date.isoformat() if c.due_date else None,
            "status": c.status,
            "priority_band": c.priority_band,
            "overdue": bool(c.due_date and c.due_date < today),
        }
        for c in rows
    ]


def overdue_permits(db: Session, audit: Audit) -> List[dict]:
    """Live permits whose validity has already expired at this site.

    A permit past its end date with work still open against it is exactly the
    kind of thing the auditor should walk in already knowing about.
    """
    try:
        rows = db.execute(
            text(
                # permits_to_work has no reference column — PTW-0001 is derived
                # everywhere else in the codebase, so it is derived here too.
                "SELECT p.id, p.work_description, p.validity_end, p.workflow_status "
                "  FROM permits_to_work p "
                " WHERE p.organisation_id = :org "
                "   AND p.validity_end IS NOT NULL "
                "   AND p.validity_end < :now "
                "   AND LOWER(COALESCE(p.workflow_status, '')) IN "
                "       ('approved', 'active', 'issued', 'in_progress', 'suspended') "
                " ORDER BY p.validity_end ASC "
                " LIMIT 25"
            ),
            {"org": audit.organisation_id, "now": datetime.utcnow()},
        ).mappings().all()
    except Exception:
        logger.exception("Could not read overdue permits for the brief pack")
        return []
    return [
        {
            "permit_id": r["id"],
            "permit_ref": f"PTW-{r['id']:04d}",
            "work_description": r["work_description"],
            "validity_end": r["validity_end"].isoformat() if r["validity_end"] else None,
            "workflow_status": r["workflow_status"],
            "days_expired": (datetime.utcnow() - r["validity_end"]).days if r["validity_end"] else None,
        }
        for r in rows
    ]


def highest_risk_areas(db: Session, audit: Audit) -> List[dict]:
    """Sections that failed hardest last time, so the checklist can lead with them."""
    prev = _previous_audits(db, audit, limit=2)
    if not prev:
        return []
    rows = (
        db.query(AuditFinding.section, AuditFinding.classification)
        .filter(AuditFinding.audit_id.in_([p.id for p in prev]))
        .filter(AuditFinding.classification.in_((MINOR_NC, MAJOR_NC, CRITICAL)))
        .all()
    )
    weight = {MINOR_NC: 1, MAJOR_NC: 3, CRITICAL: 5}
    tally: dict = {}
    for section, classification in rows:
        key = section or "General"
        tally[key] = tally.get(key, 0) + weight.get(classification, 1)
    return [
        {"section": k, "risk_weight": v}
        for k, v in sorted(tally.items(), key=lambda kv: kv[1], reverse=True)
    ]


def build(db: Session, audit: Audit) -> dict:
    """The whole pack, as a plain dict ready to be stored on the audit."""
    prev = _previous_audits(db, audit, limit=1)
    last = prev[0] if prev else None
    programme = (
        db.query(AuditProgramme)
        .filter_by(organisation_id=audit.organisation_id, site_id=audit.site_id)
        .first()
    )

    findings = previous_findings(db, audit)
    actions = open_actions(db, audit)
    permits = overdue_permits(db, audit)
    areas = highest_risk_areas(db, audit)

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "audit_ref": audit.audit_ref,
        "site_name": audit.site_name,
        "checklist_type": audit.checklist_type,
        "trigger": {
            "key": audit.trigger_type,
            **audit_programme.TRIGGERS.get(audit.trigger_type or "scheduled_programme", {}),
        },
        "risk_band": audit.risk_band or (programme.risk_band if programme else None),
        "current_score": {
            "last_audit_ref": last.audit_ref if last else None,
            "last_audit_score": last.compliance_score if last else None,
            "last_audit_band": last.score_band if last else None,
            "last_audit_rating": last.overall_rating if last else None,
            "last_audit_date": last.submitted_at.isoformat() if last and last.submitted_at else None,
        },
        "previous_findings": findings,
        "previous_finding_count": len(findings),
        "repeat_watchlist": [f for f in findings if f["was_closed"] and f["classification"] != "conformance"],
        "open_actions": actions,
        "open_action_count": len(actions),
        "overdue_actions": [a for a in actions if a["overdue"]],
        "overdue_permits": permits,
        "overdue_permit_count": len(permits),
        "highest_risk_areas": areas,
        "regulatory_guidance": _guidance_for(audit.checklist_type),
    }


# Clause references the report maps findings to. Kept here rather than in the
# checklist templates because the same clause applies across several audit types
# and duplicating it into each template is how the two drift apart.
_GUIDANCE = {
    "safety management system": [
        {"standard": "ISO 45001", "clause": "5.2", "topic": "OH&S policy"},
        {"standard": "ISO 45001", "clause": "6.1.2", "topic": "Hazard identification and risk assessment"},
        {"standard": "ISO 45001", "clause": "9.3", "topic": "Management review"},
    ],
    "fire safety": [
        {"standard": "ISO 45001", "clause": "8.2", "topic": "Emergency preparedness and response"},
        {"standard": "OSHA VPP", "clause": "1910.157", "topic": "Portable fire extinguishers"},
    ],
    "environmental": [
        {"standard": "ISO 14001", "clause": "6.1.2", "topic": "Environmental aspects"},
        {"standard": "ISO 14001", "clause": "8.2", "topic": "Emergency preparedness"},
    ],
}

_GENERIC_GUIDANCE = [
    {"standard": "ISO 45001", "clause": "8.1", "topic": "Operational planning and control"},
    {"standard": "ISO 45001", "clause": "9.1", "topic": "Monitoring, measurement, analysis and evaluation"},
]


def _guidance_for(checklist_type: Optional[str]) -> List[dict]:
    key = (checklist_type or "").strip().lower()
    for k, items in _GUIDANCE.items():
        if k in key:
            return items
    return _GENERIC_GUIDANCE


def due_date(audit: Audit) -> Optional[str]:
    """When the pack should have been generated — seven days before the visit."""
    d = audit_programme.brief_pack_due(audit.scheduled_date)
    return d.isoformat() if d else None


def is_due(audit: Audit) -> bool:
    """True once the pack's generation date has arrived."""
    d = audit_programme.brief_pack_due(audit.scheduled_date)
    if d is None:
        return True
    return datetime.utcnow().date() >= d - timedelta(days=0)
