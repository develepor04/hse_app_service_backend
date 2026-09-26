from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.audit import Audit
from app.models.safety_walk import SafetyWalk


@dataclass
class AuditReadinessResult:
    score: float
    label: str
    walk_count: int
    audit_count: int
    note: str


def compute_audit_readiness(db: Session, org_id: int | None) -> AuditReadinessResult:
    """All-time blend of the legacy web/Excel-imported SafetyWalk.compliance_rating
    (0-5) and the mobile Auditor app's Audit.compliance_score (0-100, the only
    source mobile ever writes to) — single source of truth shared by the
    Compliance page and the Dashboard leading-indicators panel so both always
    show the same score for the same organisation. Deliberately all-time
    (not windowed to a selected period): this is meant to read as the org's
    overall audit/inspection posture, not a trend for whatever date range
    happens to be selected elsewhere on screen."""

    def _org(query, model):
        if org_id is not None:
            return query.filter(model.organisation_id == org_id)
        return query

    avg_walk = _org(db.query(func.avg(SafetyWalk.compliance_rating)), SafetyWalk).scalar()
    walk_count = _org(
        db.query(SafetyWalk).filter(SafetyWalk.compliance_rating.isnot(None)), SafetyWalk
    ).count()

    avg_audit = (
        _org(db.query(func.avg(Audit.compliance_score)), Audit)
        .filter(Audit.compliance_score.isnot(None))
        .scalar()
    )
    audit_count = (
        _org(db.query(Audit), Audit).filter(Audit.compliance_score.isnot(None)).count()
    )

    components = []
    if avg_walk is not None:
        components.append(float(avg_walk) / 5 * 100)
    if avg_audit is not None:
        components.append(float(avg_audit))

    score = round(sum(components) / len(components)) if components else 0
    label = "Ready" if score >= 80 else ("Needs Attention" if score >= 60 else "Not Ready")
    note = (
        f"From {walk_count} rated safety walk{'s' if walk_count != 1 else ''} "
        f"and {audit_count} scored audit{'s' if audit_count != 1 else ''}"
        if (walk_count or audit_count) else "No rated safety walks or scored audits yet"
    )

    return AuditReadinessResult(
        score=score, label=label, walk_count=walk_count, audit_count=audit_count, note=note,
    )
