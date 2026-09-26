"""WF-05 step 10 · cross-site trend review and repeat-finding analysis.

"Compares against previous audits and against peer sites, and fires the re-audit
trigger when the rules are met." Owned by the Admin and the Safety Manager, on
the web console, because comparison is a reading job and the screen is bigger.

The one question this module exists to answer that a per-audit view cannot: is
the same thing failing in more than one place? A Minor NC at one site is a lapse.
The same Minor NC at six sites is a systemic failure that no individual audit
report can see, because each one only knows about itself.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.audit import Audit, AuditFinding
from app.services.audit_scoring import (
    CLASSIFICATIONS, CRITICAL, MAJOR_NC, MINOR_NC, RE_AUDIT_THRESHOLD,
    is_non_conformance, overall_rating, score_band,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_WINDOW_DAYS = 365


def _completed(db: Session, org_id: Optional[int], since: datetime) -> List[Audit]:
    return (
        db.query(Audit)
        .filter(
            Audit.organisation_id == org_id,
            Audit.compliance_score.isnot(None),
            Audit.submitted_at.isnot(None),
            Audit.submitted_at >= since,
        )
        .order_by(Audit.submitted_at.asc())
        .all()
    )


def site_comparison(
    db: Session, org_id: Optional[int], window_days: int = DEFAULT_WINDOW_DAYS,
) -> List[dict]:
    """Every site's audit performance, side by side.

    `trend` is the change between a site's two most recent audits, not a fitted
    line: with two or three audits a year, a regression says more about the
    arithmetic than about the site.
    """
    since = datetime.utcnow() - timedelta(days=window_days)
    audits = _completed(db, org_id, since)

    by_site: Dict[Any, List[Audit]] = defaultdict(list)
    for a in audits:
        by_site[a.site_id or a.site_name].append(a)

    finding_counts = _finding_counts_by_audit(db, [a.id for a in audits])

    rows = []
    for key, site_audits in by_site.items():
        ordered = sorted(site_audits, key=lambda x: x.submitted_at or datetime.min)
        latest = ordered[-1]
        previous = ordered[-2] if len(ordered) > 1 else None
        scores = [a.compliance_score for a in ordered if a.compliance_score is not None]
        avg = round(sum(scores) / len(scores), 1) if scores else 0.0

        counts: Dict[str, int] = defaultdict(int)
        for a in ordered:
            for k, v in finding_counts.get(a.id, {}).items():
                counts[k] += v

        # Below 65% twice running is a re-audit trigger in its own right.
        recent_two = scores[-2:]
        twice_below = len(recent_two) == 2 and all(s < RE_AUDIT_THRESHOLD for s in recent_two)

        rows.append({
            "site_id": latest.site_id,
            "site_name": latest.site_name,
            "risk_band": latest.risk_band,
            "audits_in_window": len(ordered),
            "latest_score": latest.compliance_score,
            "latest_band": latest.score_band or score_band(latest.compliance_score),
            "latest_rating": latest.overall_rating,
            "latest_audit_ref": latest.audit_ref,
            "latest_audit_date": latest.submitted_at.isoformat() if latest.submitted_at else None,
            "previous_score": previous.compliance_score if previous else None,
            "trend": (
                round(latest.compliance_score - previous.compliance_score, 1)
                if previous and previous.compliance_score is not None
                and latest.compliance_score is not None else None
            ),
            "average_score": avg,
            "finding_counts": dict(counts),
            "major_or_critical": counts.get(MAJOR_NC, 0) + counts.get(CRITICAL, 0),
            "open_re_audit": bool(latest.re_audit_required)
                             and latest.re_audit_decision not in ("waived", "scheduled"),
            "below_threshold_twice": twice_below,
        })

    # Worst first: this screen exists to find the sites that need attention.
    rows.sort(key=lambda r: (r["latest_score"] if r["latest_score"] is not None else 999))
    return rows


def _finding_counts_by_audit(db: Session, audit_ids: List[int]) -> Dict[int, Dict[str, int]]:
    if not audit_ids:
        return {}
    rows = (
        db.query(AuditFinding.audit_id, AuditFinding.classification)
        .filter(AuditFinding.audit_id.in_(audit_ids))
        .all()
    )
    out: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for audit_id, classification in rows:
        out[audit_id][classification] += 1
    return {k: dict(v) for k, v in out.items()}


def repeat_findings(
    db: Session, org_id: Optional[int], window_days: int = DEFAULT_WINDOW_DAYS,
) -> List[dict]:
    """Findings that came back, and findings appearing at more than one site.

    Two different failures, deliberately in one list because they are the same
    question asked at two scales: is this control actually working anywhere?
    """
    since = datetime.utcnow() - timedelta(days=window_days)

    rows = (
        db.query(
            AuditFinding.title,
            AuditFinding.classification,
            AuditFinding.section,
            AuditFinding.is_repeat,
            Audit.site_id,
            Audit.site_name,
            Audit.audit_ref,
            Audit.submitted_at,
        )
        .join(Audit, Audit.id == AuditFinding.audit_id)
        .filter(
            Audit.organisation_id == org_id,
            Audit.submitted_at >= since,
        )
        .all()
    )

    grouped: Dict[str, dict] = {}
    for title, classification, section, is_repeat, site_id, site_name, ref, when in rows:
        if not is_non_conformance(classification):
            continue
        entry = grouped.setdefault(title, {
            "title": title,
            "section": section,
            "worst_classification": classification,
            "occurrences": 0,
            "sites": set(),
            "site_names": set(),
            "repeat_occurrences": 0,
            "audit_refs": [],
            "last_seen": None,
        })
        entry["occurrences"] += 1
        if site_id is not None:
            entry["sites"].add(site_id)
        if site_name:
            entry["site_names"].add(site_name)
        if is_repeat:
            entry["repeat_occurrences"] += 1
        if ref:
            entry["audit_refs"].append(ref)
        if when and (entry["last_seen"] is None or when > entry["last_seen"]):
            entry["last_seen"] = when
        if CLASSIFICATIONS[classification]["severity"] > \
                CLASSIFICATIONS[entry["worst_classification"]]["severity"]:
            entry["worst_classification"] = classification

    out = []
    for e in grouped.values():
        site_count = len(e["sites"]) or len(e["site_names"])
        # Only worth surfacing if it recurred — either at the same site over
        # time, or across more than one site at once.
        if e["repeat_occurrences"] == 0 and site_count < 2 and e["occurrences"] < 2:
            continue
        out.append({
            "title": e["title"],
            "section": e["section"],
            "worst_classification": e["worst_classification"],
            "occurrences": e["occurrences"],
            "site_count": site_count,
            "site_names": sorted(e["site_names"]),
            "repeat_occurrences": e["repeat_occurrences"],
            "audit_refs": e["audit_refs"][:8],
            "last_seen": e["last_seen"].isoformat() if e["last_seen"] else None,
            "systemic": site_count >= 2,
        })

    out.sort(key=lambda r: (-r["site_count"], -r["occurrences"]))
    return out


def organisation_summary(
    db: Session, org_id: Optional[int], window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict:
    """The headline numbers for the oversight screen."""
    since = datetime.utcnow() - timedelta(days=window_days)
    audits = _completed(db, org_id, since)
    scores = [a.compliance_score for a in audits if a.compliance_score is not None]
    counts = _finding_counts_by_audit(db, [a.id for a in audits])

    totals: Dict[str, int] = defaultdict(int)
    for c in counts.values():
        for k, v in c.items():
            totals[k] += v

    ratings: Dict[str, int] = defaultdict(int)
    for a in audits:
        if a.overall_rating:
            ratings[a.overall_rating] += 1

    open_re_audits = (
        db.query(Audit.id)
        .filter(
            Audit.organisation_id == org_id,
            Audit.re_audit_required.is_(True),
            Audit.re_audit_decision.notin_(("waived", "scheduled")),
        )
        .count()
    )

    open_findings = (
        db.query(AuditFinding.id)
        .join(Audit, Audit.id == AuditFinding.audit_id)
        .filter(
            Audit.organisation_id == org_id,
            AuditFinding.classification.in_((MINOR_NC, MAJOR_NC, CRITICAL)),
            AuditFinding.status.notin_(("verified", "closed")),
        )
        .count()
    )

    avg = round(sum(scores) / len(scores), 1) if scores else 0.0
    return {
        "window_days": window_days,
        "audits_completed": len(audits),
        "average_score": avg,
        "average_band": score_band(avg),
        "finding_counts": dict(totals),
        "ratings": dict(ratings),
        "open_non_conformances": open_findings,
        "open_re_audit_decisions": open_re_audits,
        "audits_closed": sum(1 for a in audits if a.closed_at),
        "audits_open": sum(1 for a in audits if not a.closed_at),
    }
