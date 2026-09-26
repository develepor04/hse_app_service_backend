from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.contractor import ContractorCompany, ContractorScorecard
from app.models.employee import Employee
from app.models.incident import Incident
from app.models.organisation import Organisation
from app.models.permit_to_work import PermitToWork
from app.utils.tenant import org_scoped_join

CONTRACTOR_TYPE_PATTERN = "%contract%"

# Admin-configurable via /org-admin/settings/formula-config (Organisation.formula_config
# -> "contractor_score"); these are the built-in defaults used when an org hasn't set any.
DEFAULT_CONTRACTOR_WEIGHTS = {
    "violation_penalty_per_violation": 0.5,
    "violation_penalty_cap": 3.0,
    "incident_penalty_multiplier": 3.0,
    "incident_penalty_cap": 7.0,
}


def get_contractor_weights(db: Session, org_id: int | None) -> dict:
    if org_id is not None:
        org = db.query(Organisation).filter(Organisation.id == org_id).first()
        if org and org.formula_config and org.formula_config.get("contractor_score"):
            return {**DEFAULT_CONTRACTOR_WEIGHTS, **org.formula_config["contractor_score"]}
    return dict(DEFAULT_CONTRACTOR_WEIGHTS)


@dataclass
class ContractorRiskResult:
    has_contractors: bool
    contractor_employees: int
    total_employees: int
    contractor_incidents: int
    total_org_incidents: int
    contractor_violations: int
    relative_risk: float
    violation_penalty: float
    incident_penalty: float
    score_10: float
    score_pct: float
    label: str


def compute_contractor_risk(db: Session, org_id: int | None) -> ContractorRiskResult:
    """Single source of truth for the Contractor Risk Score, shared by the
    dashboard leading-indicators panel and the Vendors/Contractors page so both
    always display the same number for the same organisation."""

    weights = get_contractor_weights(db, org_id)

    def _org(query, model):
        if org_id is not None:
            return query.filter(model.organisation_id == org_id)
        return query

    contractor_employees = int(
        _org(db.query(Employee), Employee)
        .filter(func.lower(Employee.employment_type).like(CONTRACTOR_TYPE_PATTERN))
        .count()
    )
    total_employees = int(_org(db.query(Employee), Employee).count())

    total_org_incidents = int(_org(db.query(Incident), Incident).count())

    contractor_incidents = int(
        _org(db.query(func.count(Incident.id)), Incident)
        .join(Employee, org_scoped_join(Incident.reported_by == Employee.id, Employee.organisation_id, org_id))
        .filter(func.lower(Employee.employment_type).like(CONTRACTOR_TYPE_PATTERN))
        .scalar()
        or 0
    )

    # Violations must be scoped to permits issued by a contractor — an org-wide
    # violation count dilutes the score with permits that have nothing to do
    # with contractors, and saturates the penalty cap for every organisation.
    contractor_violations = int(
        _org(db.query(func.count(PermitToWork.id)), PermitToWork)
        .join(Employee, org_scoped_join(PermitToWork.issued_by == Employee.id, Employee.organisation_id, org_id))
        .filter(
            PermitToWork.deviation_reported == "Yes",
            func.lower(Employee.employment_type).like(CONTRACTOR_TYPE_PATTERN),
        )
        .scalar()
        or 0
    )

    violation_penalty = min(
        weights["violation_penalty_cap"],
        contractor_violations * weights["violation_penalty_per_violation"],
    )

    if contractor_employees == 0:
        # No contractor workforce recorded for this org — a score would be
        # fabricated from unrelated data, so report explicitly that none exists
        # instead of one controller returning a fake 10/10 and another a
        # violation-only score.
        return ContractorRiskResult(
            has_contractors=False,
            contractor_employees=0,
            total_employees=total_employees,
            contractor_incidents=0,
            total_org_incidents=total_org_incidents,
            contractor_violations=contractor_violations,
            relative_risk=0.0,
            violation_penalty=0.0,
            incident_penalty=0.0,
            score_10=0.0,
            score_pct=0.0,
            label="No Contractors",
        )

    if total_org_incidents == 0:
        relative_risk = 0.0
        incident_penalty = 0.0
    else:
        cont_inc_rate = contractor_incidents / contractor_employees
        org_inc_rate = total_org_incidents / max(total_employees, 1)
        relative_risk = round(cont_inc_rate / org_inc_rate, 2) if org_inc_rate > 0 else 0.0
        incident_penalty = min(
            weights["incident_penalty_cap"],
            relative_risk * weights["incident_penalty_multiplier"],
        )

    score_10 = round(max(0.0, 10.0 - incident_penalty - violation_penalty), 1)
    score_pct = round(score_10 * 10, 1)
    label = "High" if score_10 < 5 else ("Medium" if score_10 < 8 else "Low")

    return ContractorRiskResult(
        has_contractors=True,
        contractor_employees=contractor_employees,
        total_employees=total_employees,
        contractor_incidents=contractor_incidents,
        total_org_incidents=total_org_incidents,
        contractor_violations=contractor_violations,
        relative_risk=relative_risk,
        violation_penalty=violation_penalty,
        incident_penalty=incident_penalty,
        score_10=score_10,
        score_pct=score_pct,
        label=label,
    )


@dataclass
class ContractorSafetyScoreResult:
    score: Optional[float]
    company_count: int


def compute_contractor_safety_score(db: Session, org_id: int | None) -> ContractorSafetyScoreResult:
    """Average of each contractor company's latest scorecard (0-100) — single
    source of truth shared by the dashboard leading-indicators panel and the
    Vendors page, same reasoning as compute_contractor_risk above."""

    def _org(query, model):
        if org_id is not None:
            return query.filter(model.organisation_id == org_id)
        return query

    company_ids = [r[0] for r in _org(db.query(ContractorCompany.id), ContractorCompany).all()]
    if not company_ids:
        return ContractorSafetyScoreResult(score=None, company_count=0)

    scorecard_rows = (
        _org(db.query(ContractorScorecard), ContractorScorecard)
        .filter(ContractorScorecard.contractor_company_id.in_(company_ids))
        .order_by(ContractorScorecard.period_year.desc(), ContractorScorecard.period_quarter.desc())
        .all()
    )
    latest_scores: dict[int, float] = {}
    for row in scorecard_rows:
        latest_scores.setdefault(row.contractor_company_id, float(row.score))

    if not latest_scores:
        return ContractorSafetyScoreResult(score=None, company_count=0)

    return ContractorSafetyScoreResult(
        score=round(sum(latest_scores.values()) / len(latest_scores), 1),
        company_count=len(latest_scores),
    )
