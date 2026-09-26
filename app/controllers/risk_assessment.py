"""WF-01 Flow B · the ten steps of a risk assessment.

Flow A — the hazard register — answers "something is dangerous, deal with it".
This answers "we are about to do a job, is it safe to start". The spec makes
the second a precondition of the first kind of work happening at all: no
approved assessment, no permit.

Where the hard stops are, and why each is a stop rather than a warning:

  02  All ten categories must be answered before anything can be scored. The
      spec: "a category cannot be silently skipped". An assessment that scored
      six categories and quietly ignored four would read as complete and be
      worth less than nothing.

  08  The residual score decides, and 15 or above cannot be self-approved. The
      supervisor who wrote the assessment is not the person who signs off that
      the work may proceed under it.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import CurrentUser, get_current_user
from app.controllers.workflow_common import (
    MANAGER_ROLES, SUPERVISOR_ROLES, employee_id_for, require_role,
)
from app.models.risk_assessment import RiskAssessment, RiskAssessmentHazard
from app.schemas.risk_assessment import (
    AssessmentApprove, AssessmentCreate, AssessmentOut, CategoryAnswer,
    CategoryControl, CategoryOut,
)
from app.services import risk_assessment as svc
from app.services import control_hierarchy
from app.services import risk_scoring
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/risk-assessments", tags=["Risk Assessment (WF-01 Flow B)"])


def _get(db: Session, aid: int, org_id: Optional[int]) -> RiskAssessment:
    row = (
        db.query(RiskAssessment)
        .filter(RiskAssessment.id == aid, RiskAssessment.organisation_id == org_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"Risk assessment {aid} not found")
    return row


def _categories(db: Session, aid: int) -> List[RiskAssessmentHazard]:
    return (
        db.query(RiskAssessmentHazard)
        .filter(RiskAssessmentHazard.assessment_id == aid)
        .order_by(RiskAssessmentHazard.id)
        .all()
    )


def _respond(db: Session, row: RiskAssessment) -> AssessmentOut:
    cats = _categories(db, row.id)
    step = svc.step_for(row.status)
    return AssessmentOut(
        id=row.id,
        reference=f"RA-{row.id}",
        activity=row.activity,
        task_description=row.task_description,
        site_id=row.site_id,
        location_station_id=row.location_station_id,
        status=row.status,
        step=step,
        step_label=svc.STEP_LABEL.get(step) if step else None,
        outstanding_categories=svc.unanswered(cats),
        uplift_total=row.uplift_total or 0,
        inherent_score=row.inherent_score,
        adjusted_score=row.adjusted_score,
        band=row.band,
        residual_score=row.residual_score,
        residual_band=row.residual_band,
        blocks_work=bool(row.blocks_work),
        approval_route=row.approval_route,
        approved_by=row.approved_by,
        approved_at=row.approved_at,
        review_frequency=row.review_frequency,
        review_due_at=row.review_due_at,
        archived_at=row.archived_at,
        created_by=row.created_by,
        created_at=row.created_at,
        categories=[CategoryOut.model_validate(c) for c in cats],
    )


# ── 01 SCOPE ─────────────────────────────────────────────────────────────────

@router.post("", response_model=AssessmentOut, status_code=201)
@router.post("/", response_model=AssessmentOut, status_code=201)
def start_assessment(
    payload: AssessmentCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 01. The supervisor scopes the activity; the ten categories appear.

    Creating all ten up front is the mechanism behind the spec's completeness
    rule. An assessor who adds categories as they think of them will never
    think of the one that was not on their mind, which is exactly the hazard
    the checklist exists to catch.
    """
    require_role(current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES, "start a risk assessment")

    row = RiskAssessment(
        organisation_id=current_user.org_id,
        activity=payload.activity,
        task_description=payload.task_description,
        site_id=payload.site_id,
        location_station_id=payload.location_station_id,
        status="identifying",
        uplift_no_valid_rams=int(payload.no_valid_rams),
        uplift_new_worker=int(payload.new_worker),
        uplift_night_shift=int(payload.night_shift),
        uplift_temporary_control=int(payload.temporary_control),
        created_by=employee_id_for(db, current_user.user_id),
    )
    db.add(row)
    db.flush()

    # Link each of the ten to this tenant's own category row where one exists,
    # so a hazard promoted to the register lands in the right bucket.
    local = svc.resolve_category_ids(db, current_user.org_id)
    for c in svc.CATEGORIES:
        db.add(RiskAssessmentHazard(
            assessment_id=row.id,
            organisation_id=current_user.org_id,
            category_key=c.key,
            category_name=c.name,
            category_id=local.get(c.key),
        ))
    db.commit()
    db.refresh(row)
    return _respond(db, row)


@router.get("", response_model=List[AssessmentOut])
@router.get("/", response_model=List[AssessmentOut])
def list_assessments(
    mine_only: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    q = db.query(RiskAssessment).filter(RiskAssessment.organisation_id == current_user.org_id)
    if mine_only:
        q = q.filter(RiskAssessment.created_by == employee_id_for(db, current_user.user_id))
    return [_respond(db, r) for r in q.order_by(RiskAssessment.id.desc()).limit(200).all()]


# ── 02-03 IDENTIFY ───────────────────────────────────────────────────────────

@router.patch("/{aid}/categories/{key}", response_model=AssessmentOut)
def answer_category(
    aid: int,
    key: str,
    payload: CategoryAnswer,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Steps 02-03. Answer one category, and score it if a hazard is present.

    A "No" is a complete answer and the common one. A "Yes" without a
    likelihood and severity is refused: an unscored hazard cannot drive the
    assessment, so accepting it would let the worst thing found be invisible to
    the score.
    """
    require_role(current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES, "answer a risk assessment")
    row = _get(db, aid, current_user.org_id)
    if row.approved_at:
        raise HTTPException(status_code=409, detail="This assessment is approved. Reopen it to change an answer.")

    cat = next((c for c in _categories(db, aid) if c.category_key == key), None)
    if not cat:
        raise HTTPException(status_code=404, detail=f"'{key}' is not one of the ten categories")

    present = payload.hazard_present.strip().title()
    if present not in ("Yes", "No"):
        raise HTTPException(status_code=400, detail="hazard_present must be Yes or No")

    if present == "Yes" and not (payload.likelihood and payload.severity):
        raise HTTPException(
            status_code=400,
            detail="A hazard marked present needs a likelihood and a severity — an unscored hazard cannot drive the assessment.",
        )

    cat.hazard_present = present
    cat.description = payload.description
    cat.likelihood = payload.likelihood if present == "Yes" else None
    cat.severity = payload.severity if present == "Yes" else None
    lik = risk_scoring.LIKELIHOOD.get((cat.likelihood or "").lower())
    sev = risk_scoring.SEVERITY.get((cat.severity or "").lower())
    cat.inherent_score = (lik * sev) if lik and sev else None

    db.commit()
    db.refresh(row)
    return _respond(db, row)


# ── 03-05 SCORE ──────────────────────────────────────────────────────────────

@router.post("/{aid}/score", response_model=AssessmentOut)
def score_assessment(
    aid: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Steps 03-05. Inherent risk, uplifts, band — refused while any category is blank."""
    require_role(current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES, "score a risk assessment")
    row = _get(db, aid, current_user.org_id)
    cats = _categories(db, aid)

    missing = svc.unanswered(cats)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    f"{len(missing)} of the ten categories have not been answered. "
                    "Every category needs a Yes or a No before this can be scored."
                ),
                "reason": "categories_incomplete",
                "outstanding": missing,
            },
        )

    result = svc.score_assessment(cats, uplifts={
        "no_valid_rams": bool(row.uplift_no_valid_rams),
        "new_worker": bool(row.uplift_new_worker),
        "night_shift": bool(row.uplift_night_shift),
        "temporary_control": bool(row.uplift_temporary_control),
    })
    row.inherent_score = result.inherent_score
    row.adjusted_score = result.adjusted_score
    row.uplift_total = result.uplift_total
    row.band = result.band
    row.band_colour = result.colour
    row.review_frequency = result.review_frequency
    row.status = "scored"
    db.commit()
    db.refresh(row)
    return _respond(db, row)


# ── 06-07 CONTROL ────────────────────────────────────────────────────────────

@router.patch("/{aid}/categories/{key}/control", response_model=AssessmentOut)
def set_control(
    aid: int,
    key: str,
    payload: CategoryControl,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Steps 06-07. The control by hierarchy, its owner, and the residual score."""
    require_role(current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES, "set controls")
    row = _get(db, aid, current_user.org_id)
    cat = next((c for c in _categories(db, aid) if c.category_key == key), None)
    if not cat:
        raise HTTPException(status_code=404, detail=f"'{key}' is not one of the ten categories")
    if cat.hazard_present != "Yes":
        raise HTTPException(status_code=400, detail="Only a category with a hazard present takes a control")
    if control_hierarchy.normalise(payload.control_hierarchy) is None:
        raise HTTPException(
            status_code=400,
            detail=f"control_hierarchy must be one of: {', '.join(control_hierarchy.HIERARCHY)}",
        )

    cat.control_hierarchy = payload.control_hierarchy
    cat.control_description = payload.control_description
    cat.control_owner_id = payload.control_owner_id
    cat.control_due_date = payload.control_due_date
    cat.residual_likelihood = payload.residual_likelihood
    cat.residual_severity = payload.residual_severity
    lik = risk_scoring.LIKELIHOOD.get((payload.residual_likelihood or "").lower())
    sev = risk_scoring.SEVERITY.get((payload.residual_severity or "").lower())
    cat.residual_score = (lik * sev) if lik and sev else None

    if row.status == "scored":
        row.status = "controls_planned"

    # WF-01 · "Flags PPE-only with a mandatory review notice." PPE leaves the
    # hazard fully intact, so choosing it is a decision somebody senior should
    # see rather than one the system accepts in silence.
    if control_hierarchy.is_ppe_only(payload.control_hierarchy):
        svc.flag_for_review(
            db, row,
            f"{cat.category_name} is controlled by PPE alone — mandatory review",
            commit=False,
        )

    db.commit()
    db.refresh(row)
    return _respond(db, row)


# ── 08 APPROVE ───────────────────────────────────────────────────────────────

@router.post("/{aid}/submit", response_model=AssessmentOut)
def submit_for_approval(
    aid: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 08. Work out the residual score and route it for sign-off."""
    require_role(current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES, "submit a risk assessment")
    row = _get(db, aid, current_user.org_id)
    cats = _categories(db, aid)

    unscored = [c.category_key for c in cats if c.hazard_present == "Yes" and c.residual_score is None]
    if unscored:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Every hazard found needs a control and a residual score before sign-off.",
                "reason": "controls_incomplete",
                "outstanding": unscored,
            },
        )

    score, band, route, blocks = svc.residual_for(cats)
    row.residual_score = score
    row.residual_band = band
    row.approval_route = route
    row.blocks_work = int(blocks)
    row.status = "pending_approval"
    db.commit()
    db.refresh(row)
    return _respond(db, row)


@router.post("/{aid}/approve", response_model=AssessmentOut)
def approve(
    aid: int,
    payload: AssessmentApprove,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 08. The signature that lets the work start.

    A residual of 15 or above needs the Safety Manager and cannot be signed by
    the supervisor who wrote it — the spec's rule, and the reason the route is
    stored rather than recomputed at the point of clicking.
    """
    row = _get(db, aid, current_user.org_id)
    if row.status != "pending_approval":
        raise HTTPException(status_code=400, detail="This assessment is not awaiting approval")

    if row.approval_route in (svc.ROUTE_SAFETY_MANAGER, svc.ROUTE_EXECUTIVE):
        require_role(current_user.role, MANAGER_ROLES, f"approve a {row.residual_band} residual risk")
    else:
        require_role(current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES, "approve a risk assessment")

    if not payload.approved:
        row.status = "controls_planned"
        row.approval_notes = payload.notes
        db.commit()
        db.refresh(row)
        return _respond(db, row)

    row.approved_by = employee_id_for(db, current_user.user_id)
    row.approved_at = datetime.now()
    row.approval_notes = payload.notes
    row.status = "approved"
    row.review_due_at = svc.review_due(row.review_frequency)
    # Approval clears any outstanding flag — somebody has now looked.
    row.flagged_for_review = 0
    row.review_due_by = None

    # B -> A. Every hazard the checklist found joins the register, so it is
    # tracked as a standing condition rather than living only inside this
    # assessment. Idempotent, which matters because an assessment can be
    # reopened and approved again.
    created = svc.populate_register(db, row, _categories(db, row.id), commit=False)

    db.commit()
    db.refresh(row)
    out = _respond(db, row)
    if created:
        logger.info(
            "RA-%s approved; %s hazard(s) added to the register: %s",
            row.id, len(created), created,
        )
    return out


# ── 09-10 MONITOR / ARCHIVE ──────────────────────────────────────────────────

@router.post("/{aid}/reopen", response_model=AssessmentOut)
def reopen(
    aid: int,
    reason: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 09. Something changed, so the assessment is no longer trustworthy."""
    require_role(current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES, "reopen a risk assessment")
    row = _get(db, aid, current_user.org_id)
    row.status = "controls_planned"
    row.approved_at = None
    row.approved_by = None
    row.reopened_reason = reason
    row.reopened_at = datetime.now()
    db.commit()
    db.refresh(row)
    return _respond(db, row)


@router.post("/{aid}/archive", response_model=AssessmentOut)
def archive(
    aid: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 10. Kept for the regulator; no longer a live authorisation."""
    require_role(current_user.role, MANAGER_ROLES, "archive a risk assessment")
    row = _get(db, aid, current_user.org_id)
    if not row.approved_at:
        raise HTTPException(status_code=400, detail="Only an approved assessment can be archived")
    row.status = "archived"
    row.archived_at = datetime.now()
    db.commit()
    db.refresh(row)
    return _respond(db, row)


@router.get("/{aid}", response_model=AssessmentOut)
def get_assessment(
    aid: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    return _respond(db, _get(db, aid, current_user.org_id))
