"""WF-05 · what starts an audit, and how often.

"Audits are not booked by hand. The system generates the annual programme from
each site's risk band, and that band is driven by the site's own safety
performance score. A site that deteriorates gets audited more often,
automatically."

The band thresholds here are the same numbers `hse_formulae.sps_band` already
uses, deliberately: the audit programme reads the KPI engine's score rather than
inventing a second one, so a site cannot be critical on the dashboard and low on
the audit calendar at the same time.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.audit import Audit, AuditProgramme
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Six things trigger an audit
# ══════════════════════════════════════════════════════════════════════════════

TRIGGERS: Dict[str, dict] = {
    "scheduled_programme": {
        "label": "Scheduled programme",
        "detail": "The annual calendar generated from the site risk band.",
        "requires_notice": True,
    },
    "post_incident": {
        "label": "After an incident",
        "detail": "A reactive inspection following a significant event.",
        "requires_notice": False,
    },
    "management_directed": {
        "label": "Management directed",
        "detail": "Requested by management outside the normal cycle.",
        "requires_notice": True,
    },
    "regulatory": {
        "label": "Regulatory requirement",
        "detail": "Required by an authority or for certification renewal.",
        "requires_notice": True,
    },
    "score_threshold": {
        "label": "Score threshold breach",
        "detail": "The safety performance score crosses a threshold.",
        "requires_notice": False,
    },
    "risk_spike": {
        "label": "Risk spike",
        "detail": "Predicted risk rises sharply — an unscheduled inspection is raised rather than waiting.",
        "requires_notice": False,
    },
}

# Minimum notice to the auditee, "except for unannounced inspections, which carry
# none by design".
NOTICE_DAYS = 14
# The brief pack is built this far ahead of the visit.
BRIEF_PACK_DAYS = 7


def requires_notice(trigger_type: Optional[str]) -> bool:
    return TRIGGERS.get(trigger_type or "scheduled_programme", {}).get("requires_notice", True)


# ══════════════════════════════════════════════════════════════════════════════
# Frequency by site risk band
# ══════════════════════════════════════════════════════════════════════════════

CRITICAL = "critical"
HIGH = "high"
MEDIUM = "medium"
LOW = "low"


@dataclass(frozen=True)
class BandRule:
    band: str
    label: str
    score_floor: float
    qualifying: str
    inspection_frequency: str
    inspection_days: int
    audit_frequency: str
    audit_days: int
    re_audit_trigger: str


BAND_RULES: List[BandRule] = [
    BandRule(
        band=CRITICAL, label="Critical", score_floor=75,
        qualifying="Score 75+ or any fatal/critical event in 12 months",
        inspection_frequency="monthly", inspection_days=30,
        audit_frequency="quarterly", audit_days=90,
        re_audit_trigger="Any Major non-conformance — re-audit within 30 days",
    ),
    BandRule(
        band=HIGH, label="High", score_floor=50,
        qualifying="Score 50–74 or a lost-time injury in 6 months",
        inspection_frequency="monthly", inspection_days=30,
        audit_frequency="quarterly", audit_days=90,
        re_audit_trigger="Two or more Major NCs in 12 months — re-audit within 60 days",
    ),
    BandRule(
        band=MEDIUM, label="Medium", score_floor=25,
        qualifying="Score 25–49",
        inspection_frequency="quarterly", inspection_days=90,
        audit_frequency="bi_annual", audit_days=182,
        re_audit_trigger="Overall score below 65% for two consecutive audits",
    ),
    BandRule(
        band=LOW, label="Low", score_floor=0,
        qualifying="Score 0–24, no serious event in 24 months",
        inspection_frequency="bi_annual", inspection_days=182,
        audit_frequency="annual", audit_days=365,
        re_audit_trigger="Any lost-time injury or score below 65% — upgraded to Medium",
    ),
]

RULE_BY_BAND: Dict[str, BandRule] = {r.band: r for r in BAND_RULES}

# How long after a Major NC a re-audit is owed, by the band the site sits in.
RE_AUDIT_DAYS = {CRITICAL: 30, HIGH: 60, MEDIUM: 90, LOW: 90}


def band_for_score(score: Optional[float]) -> str:
    """Map the safety performance score onto the audit programme band.

    Higher score means worse, matching the KPI engine. The four thresholds are
    `hse_formulae.sps_band`'s, collapsed from five names to the four the audit
    frequency table uses: elevated and acceptable both sit in Medium and Low
    respectively because the frequency table has no fifth row.
    """
    if score is None:
        return LOW
    for rule in BAND_RULES:
        if score >= rule.score_floor:
            return rule.band
    return LOW


def rule_for(band: Optional[str]) -> BandRule:
    return RULE_BY_BAND.get((band or LOW).lower(), RULE_BY_BAND[LOW])


def frequency_reference() -> List[dict]:
    """The frequency table, shipped to the app so it reads the same as the spec."""
    return [
        {
            "band": r.band,
            "label": r.label,
            "qualifying": r.qualifying,
            "how_often": f"{r.inspection_frequency.replace('_', '-')} inspection + "
                         f"{r.audit_frequency.replace('_', '-')} audit",
            "inspection_frequency": r.inspection_frequency,
            "audit_frequency": r.audit_frequency,
            "re_audit_trigger": r.re_audit_trigger,
        }
        for r in BAND_RULES
    ]


# ══════════════════════════════════════════════════════════════════════════════
# Building the programme
# ══════════════════════════════════════════════════════════════════════════════

def site_score(db: Session, org_id: Optional[int], site_id: Optional[int]) -> Optional[float]:
    """The site's current safety performance score, or None if it cannot be computed.

    Returns None rather than 0 on failure. Zero is the *best* possible score in
    this engine, so a failed computation defaulting to it would quietly move a
    deteriorating site onto the annual cycle.
    """
    try:
        from app.services.sps_engine import compute_sps

        end = datetime.utcnow()
        start = end - timedelta(days=90)
        result, _domains = compute_sps(db, org_id, start, end, site_id)
        return float(result.sps)
    except Exception as exc:  # pragma: no cover — the KPI engine has its own tests
        logger.warning("Could not compute SPS for site %s: %s", site_id, exc)
        return None


def refresh_site(
    db: Session,
    org_id: Optional[int],
    site_id: Optional[int],
    site_name: Optional[str] = None,
    commit: bool = True,
) -> AuditProgramme:
    """Recompute one site's band and the dates that follow from it."""
    row = (
        db.query(AuditProgramme)
        .filter(AuditProgramme.organisation_id == org_id, AuditProgramme.site_id == site_id)
        .first()
    )
    if row is None:
        row = AuditProgramme(organisation_id=org_id, site_id=site_id)
        db.add(row)

    score = site_score(db, org_id, site_id)
    band = band_for_score(score)
    rule = rule_for(band)

    if row.risk_band and row.risk_band != band:
        row.band_changed_at = datetime.utcnow()

    last_audit = (
        db.query(Audit)
        .filter(
            Audit.organisation_id == org_id,
            Audit.site_id == site_id,
            Audit.status.in_(("completed", "closed", "verified")),
        )
        .order_by(Audit.submitted_at.desc(), Audit.id.desc())
        .first()
    )

    row.site_name = site_name or row.site_name
    row.risk_band = band
    row.site_score = score
    row.inspection_frequency = rule.inspection_frequency
    row.audit_frequency = rule.audit_frequency
    row.re_audit_trigger = rule.re_audit_trigger
    row.computed_at = datetime.utcnow()
    if last_audit is not None:
        row.last_audit_at = last_audit.submitted_at or last_audit.due_date

    anchor = (row.last_audit_at or datetime.utcnow()).date()
    row.next_inspection_due = anchor + timedelta(days=rule.inspection_days)
    row.next_audit_due = anchor + timedelta(days=rule.audit_days)

    if commit:
        db.commit()
        db.refresh(row)
    return row


def refresh_org(db: Session, org_id: Optional[int]) -> List[AuditProgramme]:
    """Regenerate the whole organisation's programme, one row per site."""
    from app.models.site import Site

    sites = db.query(Site).filter(Site.organisation_id == org_id).all()
    rows = [
        refresh_site(db, org_id, s.id, s.site_name, commit=False)
        for s in sites
    ]
    db.commit()
    for r in rows:
        db.refresh(r)
    return rows


def notice_due(scheduled_date: Optional[datetime], trigger_type: Optional[str]) -> Optional[date]:
    """The date by which the auditee must have been told."""
    if not scheduled_date or not requires_notice(trigger_type):
        return None
    return (scheduled_date - timedelta(days=NOTICE_DAYS)).date()


def brief_pack_due(scheduled_date: Optional[datetime]) -> Optional[date]:
    if not scheduled_date:
        return None
    return (scheduled_date - timedelta(days=BRIEF_PACK_DAYS)).date()


def re_audit_due(band: Optional[str], from_date: Optional[date] = None) -> date:
    days = RE_AUDIT_DAYS.get((band or LOW).lower(), 90)
    return (from_date or date.today()) + timedelta(days=days)
