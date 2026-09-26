"""WF-04 · the CAPA lifecycle, all ten steps.

Source: HSE_CAPA_Lifecycle.pdf Rev 5.0.

    01 RAISE   POST /capa                         supervisor+ · any event family
    02 RAISE   (root cause is mandatory on 01 — there is no separate step)
    03 PLAN    POST /capa/{id}/plan               owner or supervisor+
               POST /capa/{id}/approve-plan       manager · High and Critical only
    04 PRIORITY (calculated at 01, re-scored weekly by the scheduler)
    05 ASSIGN  POST /capa/{id}/assign             supervisor+ · notifies the owner
    06 DO      POST /capa/{id}/start              owner
               POST /capa/{id}/progress           owner
               POST /capa/{id}/interim-check      supervisor · the 50% gate
    07 CHECK   POST /capa/{id}/evidence           owner · validated on upload
               POST /capa/{id}/evidence/upload    owner · the file itself
               POST /capa/{id}/submit             owner · hands it to validation
    08 CHECK   GET  /capa/{id}/closure-checks     anyone · the three gates
               POST /capa/{id}/independent-review not the owner
    09 CHECK   POST /capa/reviews/{review_id}     safety team · 30/60/90 days
    10 CLOSE   POST /capa/{id}/approve-closure    Safety Manager · the final gate

The controller decides *who* may act. Whether the action is allowed and what it
produces lives in app.services.capa_lifecycle, so the scheduler reaches the same
verdicts without duplicating them.

The one behaviour worth stating plainly, because it reverses what this codebase
did before: **completing an action no longer closes it**. The owner submits
evidence, the system validates it against the action type and its date, an
independent reviewer confirms it, and only then is the Safety Manager offered
the approval. That is the document's headline rule and the reason four of these
endpoints exist.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import CurrentUser, get_current_user
from app.controllers.workflow_common import (
    ALL_ELEVATED_ROLES,
    ALL_READ_ROLES,
    AUDITOR_ROLES,
    MANAGER_ROLES,
    SUPERVISOR_ROLES,
    employee_id_for,
    require_role,
    role_matches,
)
from app.models.capa_action import CapaAction
from app.models.capa_lifecycle import (
    CapaEffectivenessReview,
    CapaEvidence,
    CapaProgressNote,
)
from app.schemas.capa_workflow import (
    CapaApproveClosure,
    CapaAssign,
    CapaDetail,
    CapaEffectivenessReviewOut,
    CapaEffectivenessReviewSubmit,
    CapaEvidenceCreate,
    CapaEvidenceOut,
    CapaIndependentReview,
    CapaInterimCheck,
    CapaPlan,
    CapaPlanApproval,
    CapaProgress,
    CapaRaise,
    CapaSubmit,
)
from app.services import capa_lifecycle as lc
from app.services import capa_notify, capa_owners, media_storage
from app.services.capa_priority import prioritise
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/capa", tags=["CAPA Lifecycle"])


# ══════════════════════════════════════════════════════════════════════════════
# Parent records
# ══════════════════════════════════════════════════════════════════════════════
#
# family -> (table, status column, statuses meaning IMPROVE, the VERIFY status,
#            the priority column the CAPA type is inherited from)
#
# When the last open action on a record closes, the record leaves stage 05 for
# stage 06. When one is reopened, it goes back. Both directions matter: a record
# sitting at VERIFY with a reopened action underneath it would be verified
# against a fix that is no longer in place.
_PARENTS: Dict[str, tuple] = {
    "incident": ("incidents", "workflow_status", ("capa_open",), "pending_verification", "severity_priority"),
    "near_miss": ("near_misses", "workflow_status", ("capa_open",), "pending_verification", "assessed_priority"),
    "unsafe_act": ("unsafe_acts", "workflow_status", ("capa_open",), "pending_verification", "assessed_priority"),
    "risk": ("risk_reports", "workflow_status", ("capa_open",), "pending_verification", "assessed_priority"),
    "hazard_register": ("hazards", "register_status", ("controls_planned",), "pending_verification", None),
    "audit": ("audits", "status", ("findings_raised", "capa_open"), "pending_review", None),
    # A permit's controls are attached before issue rather than tracked as
    # corrective actions, so nothing advances. The family is accepted so a
    # finding against a permit can still raise one.
    "permit": ("permits_to_work", "workflow_status", (), None, None),
}


def _family(value: Optional[str]) -> str:
    fam = (value or "").strip().lower()
    if fam not in _PARENTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown event family '{value}'. Expected one of: {', '.join(_PARENTS)}",
        )
    return fam


def _subject_priority(db: Session, family: str, subject_id: int) -> Optional[str]:
    """The parent's P1-P5, which the CAPA type inherits when none is given."""
    table, _, _, _, prio_col = _PARENTS[family]
    if not prio_col:
        return None
    try:
        return db.execute(
            text(f"SELECT {prio_col} FROM {table} WHERE id = :id"), {"id": subject_id}
        ).scalar()
    except Exception:
        logger.exception("Could not read priority for %s %s", family, subject_id)
        return None


def _subject_exists(db: Session, family: str, subject_id: int, org_id: Optional[int]) -> bool:
    table, _, _, _, _ = _PARENTS[family]
    row = db.execute(
        text(f"SELECT organisation_id FROM {table} WHERE id = :id"), {"id": subject_id}
    ).first()
    if not row:
        return False
    return org_id is None or row[0] in (None, org_id)


def _open_capa_count(db: Session, capa: CapaAction, exclude_id: Optional[int] = None) -> int:
    """How many actions on the same parent are still open.

    Matches on subject_family/subject_id *or* incident_id, because incidents
    carry both and rows raised before migration 060's backfill may carry only
    one. Missing an open action here would advance a parent that still has work
    outstanding.
    """
    q = db.query(func.count(CapaAction.id)).filter(
        CapaAction.organisation_id == capa.organisation_id,
        func.lower(func.coalesce(CapaAction.status, "")).notin_(list(lc.TERMINAL)),
    )
    if capa.subject_family and capa.subject_id:
        q = q.filter(
            CapaAction.subject_family == capa.subject_family,
            CapaAction.subject_id == capa.subject_id,
        )
    elif capa.incident_id:
        q = q.filter(CapaAction.incident_id == capa.incident_id)
    else:
        return 0
    if exclude_id:
        q = q.filter(CapaAction.id != exclude_id)
    return q.scalar() or 0


def _advance_parent(db: Session, capa: CapaAction) -> Optional[str]:
    """Stage 05 -> 06 on the parent, once nothing is left open."""
    fam = (capa.subject_family or "").strip().lower()
    spec = _PARENTS.get(fam)
    if not spec or not capa.subject_id:
        return None
    table, col, improve, verify, _ = spec
    if not verify or not improve:
        return None
    if _open_capa_count(db, capa, exclude_id=capa.id) > 0:
        return None
    current = db.execute(
        text(f"SELECT {col} FROM {table} WHERE id = :id"), {"id": capa.subject_id}
    ).scalar()
    if (current or "") not in improve:
        return None
    db.execute(
        text(f"UPDATE {table} SET {col} = :new WHERE id = :id"),
        {"new": verify, "id": capa.subject_id},
    )
    return verify


def _return_parent_to_improve(db: Session, capa: CapaAction) -> Optional[str]:
    """The reverse, when an action reopens."""
    fam = (capa.subject_family or "").strip().lower()
    spec = _PARENTS.get(fam)
    if not spec or not capa.subject_id:
        return None
    table, col, improve, verify, _ = spec
    if not improve:
        return None
    current = db.execute(
        text(f"SELECT {col} FROM {table} WHERE id = :id"), {"id": capa.subject_id}
    ).scalar()

    # A record already sitting in IMPROVE is where it should be.
    if (current or "") in improve:
        return None

    # A record that has already been closed out is not reopened automatically.
    # Reopening a closed incident would rewrite closure statistics and the
    # statutory position off the back of a scheduled review, which is a
    # manager's call rather than a side effect. It is not left silent either:
    # a closed record with a live corrective action underneath it is exactly
    # the thing nobody would otherwise notice.
    if (current or "").lower() in ("closed", "completed"):
        capa_notify.notify_many(
            db,
            capa_notify.safety_managers(db, capa.organisation_id),
            org_id=capa.organisation_id,
            title=f"{capa.capa_ref} reopened under a closed {fam}",
            message=(
                f"The corrective action has reopened, but {fam} #{capa.subject_id} is already "
                f"closed and has not been reopened automatically. Decide whether the closure "
                f"still stands."
            ),
            category="capa_reopened",
            subject_ref=capa.capa_ref,
            type_="warning",
        )
        return None

    db.execute(
        text(f"UPDATE {table} SET {col} = :new WHERE id = :id"),
        {"new": improve[0], "id": capa.subject_id},
    )
    return improve[0]


# ══════════════════════════════════════════════════════════════════════════════
# Fetch / authorise helpers
# ══════════════════════════════════════════════════════════════════════════════

def _get(db: Session, capa_id: int, current_user: CurrentUser) -> CapaAction:
    row = (
        db.query(CapaAction)
        .filter(CapaAction.id == capa_id)
        .filter(CapaAction.organisation_id == current_user.org_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="CAPA action not found")
    return row


def _require_unlocked(capa: CapaAction) -> None:
    """Step 10 "locks the audit trail". A closed action is a record, not a form."""
    if capa.is_locked:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{capa.capa_ref or 'This action'} is closed and its audit trail is locked. "
                "Reopen it if the fix did not hold."
            ),
        )


def _is_owner(db: Session, capa: CapaAction, current_user: CurrentUser) -> bool:
    emp = employee_id_for(db, current_user.user_id)
    return emp is not None and capa.responsible_person_id == emp


def _require_owner_or_elevated(db: Session, capa: CapaAction, current_user: CurrentUser, action: str) -> None:
    if _is_owner(db, capa, current_user):
        return
    if role_matches(current_user.role, ALL_ELEVATED_ROLES):
        return
    raise HTTPException(status_code=403, detail=f"Not authorized to {action}")


def _employee_name(db: Session, employee_id: Optional[int], org_id: Optional[int] = None) -> Optional[str]:
    """Look up an employee's name. When org_id is given, only returns a name for
    an employee belonging to that org — employee ids are a global, cross-tenant
    key, so an unscoped lookup can surface another organisation's employee name
    for a stale/bad cross-org foreign key."""
    if not employee_id:
        return None
    if org_id is not None:
        return db.execute(
            text("SELECT full_name FROM employees WHERE id = :id AND organisation_id = :org_id"),
            {"id": employee_id, "org_id": org_id},
        ).scalar()
    return db.execute(
        text("SELECT full_name FROM employees WHERE id = :id"), {"id": employee_id}
    ).scalar()


def _evidence_rows(db: Session, capa_id: int) -> List[CapaEvidence]:
    return (
        db.query(CapaEvidence)
        .filter(CapaEvidence.capa_id == capa_id)
        .order_by(CapaEvidence.id.desc())
        .all()
    )


def _closure_validation(db: Session, capa: CapaAction) -> lc.ClosureValidation:
    return lc.run_closure_checks(
        action_category=capa.action_category,
        capa_created_at=capa.created_at,
        evidence_rows=_evidence_rows(db, capa.id),
        independent_review_result=capa.independent_review_result,
        independent_review_by=capa.independent_review_by,
        responsible_person_id=capa.responsible_person_id,
    )


def _next_action(capa: CapaAction, checks: lc.ClosureValidation) -> str:
    """What has to happen next, in one sentence, for the app to render."""
    status = capa.status or lc.OPEN
    if lc.is_terminal(status):
        return "Closed. Effectiveness reviews run at 30, 60 and 90 days."
    if not (capa.success_criteria or "").strip():
        return "Plan the action — success criteria are required before work starts."
    if lc.requires_plan_approval(capa.priority_band) and not capa.plan_approved_at:
        return f"Awaiting manager approval of the plan ({capa.priority_band} priority)."
    if not capa.responsible_person_id:
        return "Assign an owner."
    if status == lc.PENDING_APPROVAL:
        return "Awaiting Safety Manager approval — all three closure checks have passed."
    if status == lc.PENDING_REVIEW:
        return "Awaiting independent review — someone other than the owner must confirm it."
    if status == lc.EVIDENCE_SUBMITTED:
        failed = checks.failures()
        return "Closure blocked: " + " ".join(failed) if failed else "Ready for independent review."
    return "Implement the action and attach evidence."


def _detail(db: Session, capa: CapaAction) -> CapaDetail:
    checks = _closure_validation(db, capa)
    stage = lc.describe(capa)
    reviews = (
        db.query(CapaEffectivenessReview)
        .filter(CapaEffectivenessReview.capa_id == capa.id)
        .order_by(CapaEffectivenessReview.review_point)
        .all()
    )
    return CapaDetail(
        id=capa.id,
        capa_ref=capa.capa_ref,
        subject_family=capa.subject_family,
        subject_id=capa.subject_id,
        incident_id=capa.incident_id,
        source=capa.source,
        description=capa.description,
        root_cause_addressed=capa.root_cause_addressed,
        action_type=capa.action_type,
        action_plan=capa.action_plan,
        success_criteria=capa.success_criteria,
        action_category=capa.action_category,
        hierarchy_level=capa.hierarchy_level,
        responsible_person_id=capa.responsible_person_id,
        responsible_person_name=_employee_name(db, capa.responsible_person_id, capa.organisation_id),
        due_date=capa.due_date,
        status=capa.status,
        severity_potential=capa.severity_potential,
        systemic_risk=capa.systemic_risk,
        priority_score=capa.priority_score,
        priority_band=capa.priority_band,
        capa_type=capa.capa_type,
        capa_type_label=capa.capa_type_label,
        evidence_required=capa.evidence_required,
        priority_explanation=capa.priority_explanation,
        step=stage["step"],
        step_label=stage["step_label"],
        total_steps=stage["total_steps"],
        is_closed=stage["is_closed"],
        elapsed_percent=stage["elapsed_percent"],
        is_overdue=stage["is_overdue"],
        escalation_level=stage["escalation_level"],
        reopened_count=capa.reopened_count or 0,
        systemic_flag=bool(capa.systemic_flag),
        is_locked=bool(capa.is_locked),
        plan_approved_at=capa.plan_approved_at,
        interim_check_at=capa.interim_check_at,
        evidence_submitted_at=capa.evidence_submitted_at,
        independent_review_at=capa.independent_review_at,
        independent_review_result=capa.independent_review_result,
        closed_at=capa.closed_at,
        lesson_learned=capa.lesson_learned,
        requires_plan_approval=lc.requires_plan_approval(capa.priority_band),
        allowed_evidence_types=list(lc.allowed_evidence_types(capa.action_category)),
        closure_checks=checks.as_json(),
        evidence=[CapaEvidenceOut.model_validate(e) for e in _evidence_rows(db, capa.id)],
        effectiveness_reviews=[CapaEffectivenessReviewOut.model_validate(r) for r in reviews],
        next_action=_next_action(capa, checks),
    )


# ══════════════════════════════════════════════════════════════════════════════
# 01 RAISE
# ══════════════════════════════════════════════════════════════════════════════

@router.post("", response_model=CapaDetail, status_code=201)
@router.post("/", response_model=CapaDetail, status_code=201)
def raise_capa(
    payload: CapaRaise,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Raise a corrective action against any event family.

    The generic /capa-actions CRUD endpoint cannot do this: its schema has no
    subject_family, so it produced orphan actions linked to nothing and computed
    no priority. That is why audits could never raise one despite the audit
    verification gate checking for them.

    A root cause is mandatory here rather than at a later step — the document
    makes step 02 a hard stop ("without a linked root cause the CAPA cannot
    progress to planning"), and a required field is a cleaner way to enforce
    that than a state nothing can leave.
    """
    require_role(current_user.role, ALL_ELEVATED_ROLES, "raise a corrective action")
    fam = _family(payload.subject_family)

    if not _subject_exists(db, fam, payload.subject_id, current_user.org_id):
        raise HTTPException(status_code=404, detail=f"No {fam} with id {payload.subject_id}")

    if payload.responsible_person_id:
        owner_in_org = db.execute(
            text("SELECT id FROM employees WHERE id = :id AND organisation_id = :org_id"),
            {"id": payload.responsible_person_id, "org_id": current_user.org_id},
        ).scalar()
        if not owner_in_org:
            raise HTTPException(status_code=404, detail="No such employee")

    now = datetime.utcnow()
    prio = prioritise(
        severity_potential=payload.severity_potential,
        systemic_risk=payload.systemic_risk,
        capa_type=payload.capa_type,
        incident_priority=_subject_priority(db, fam, payload.subject_id),
        created_at=now,
    )

    capa = CapaAction(
        organisation_id=current_user.org_id,
        subject_family=fam,
        subject_id=payload.subject_id,
        # Kept in step for incidents: fourteen aggregate queries filter on it.
        incident_id=payload.subject_id if fam == "incident" else None,
        source=payload.source or ("incident" if fam == "incident" else fam),
        raised_by=employee_id_for(db, current_user.user_id),
        action_type=payload.action_type or "Corrective",
        description=payload.description,
        root_cause_addressed=payload.root_cause_addressed,
        responsible_person_id=payload.responsible_person_id,
        due_date=payload.due_date or (prio.due_date.date() if prio.due_date else None),
        status=lc.OPEN,
        severity_potential=prio.severity_potential,
        systemic_risk=prio.systemic_risk,
        priority_score=prio.priority_score,
        priority_band=prio.priority_band,
        capa_type=prio.capa_type,
        capa_type_label=prio.capa_type_label,
        target_hours=prio.target_hours,
        evidence_required=prio.evidence_required,
        priority_explanation=prio.explanation,
    )
    if payload.responsible_person_id:
        capa.assigned_by = capa.raised_by
        capa.assigned_at = now
    db.add(capa)
    db.flush()

    # "Generates the reference number" — step 01, the system column.
    capa.capa_ref = f"CAPA-{capa.id:06d}"

    if capa.responsible_person_id:
        _notify_assignment(db, capa)

    db.commit()
    db.refresh(capa)
    return _detail(db, capa)


def _notify_assignment(db: Session, capa: CapaAction) -> None:
    capa_notify.notify(
        db,
        org_id=capa.organisation_id,
        employee_id=capa.responsible_person_id,
        title=f"{capa.capa_ref or 'CAPA'} assigned to you",
        message=(
            f"{capa.description}\n"
            f"Priority {capa.priority_band or 'unscored'} · {capa.capa_type or '—'} "
            f"{capa.capa_type_label or ''} · due {capa.due_date or 'not set'}."
        ),
        category="capa_assigned",
        subject_ref=capa.capa_ref,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 03 PLAN
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/{capa_id}/plan", response_model=CapaDetail)
def plan_capa(
    capa_id: int,
    payload: CapaPlan,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 03. The plan, the resources and — critically — the success criteria.

    Success criteria had no column at all before this. They are what step 08
    measures the evidence against, so without them the closure checks have
    nothing to check and "done" means whatever the owner says it means.
    """
    capa = _get(db, capa_id, current_user)
    _require_unlocked(capa)
    _require_owner_or_elevated(db, capa, current_user, "plan this action")

    due = payload.due_date or capa.due_date
    check = lc.validate_plan(
        action_plan=payload.action_plan,
        success_criteria=payload.success_criteria,
        action_category=payload.action_category,
        due_date=due,
        created_at=capa.created_at,
        target_hours=capa.target_hours,
    )
    if not check.ok:
        raise HTTPException(status_code=400, detail={"message": "Plan rejected", "errors": check.errors})

    if payload.hierarchy_level and payload.hierarchy_level.lower() not in lc.HIERARCHY_LEVELS:
        raise HTTPException(
            status_code=400,
            detail=f"hierarchy_level must be one of: {', '.join(lc.HIERARCHY_LEVELS)}",
        )

    capa.action_plan = payload.action_plan
    capa.success_criteria = payload.success_criteria
    capa.action_category = payload.action_category.strip().lower()
    capa.hierarchy_level = (payload.hierarchy_level or "").strip().lower() or None
    capa.due_date = due
    capa.planned_at = datetime.utcnow()

    # A re-plan invalidates an approval given against the previous version.
    capa.plan_approved_by = None
    capa.plan_approved_at = None

    if lc.requires_plan_approval(capa.priority_band):
        capa_notify.notify_many(
            db,
            capa_notify.safety_managers(db, capa.organisation_id),
            org_id=capa.organisation_id,
            title=f"{capa.capa_ref} plan needs approval",
            message=(
                f"{capa.priority_band} priority action — the plan and due date need "
                f"manager approval before work starts.\n{capa.description}"
            ),
            category="capa_plan_approval",
            subject_ref=capa.capa_ref,
        )

    db.commit()
    db.refresh(capa)
    return _detail(db, capa)


@router.post("/{capa_id}/approve-plan", response_model=CapaDetail)
def approve_plan(
    capa_id: int,
    payload: CapaPlanApproval,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 03, manager row: "Approves the action plan and its due dates for High
    and Critical priority"."""
    require_role(current_user.role, MANAGER_ROLES, "approve a CAPA plan")
    capa = _get(db, capa_id, current_user)
    _require_unlocked(capa)

    if not (capa.success_criteria or "").strip():
        raise HTTPException(status_code=400, detail="There is no plan to approve yet.")

    if payload.approved:
        capa.plan_approved_by = employee_id_for(db, current_user.user_id)
        capa.plan_approved_at = datetime.utcnow()
    else:
        capa.plan_approved_by = None
        capa.plan_approved_at = None

    if capa.responsible_person_id:
        capa_notify.notify(
            db,
            org_id=capa.organisation_id,
            employee_id=capa.responsible_person_id,
            title=f"{capa.capa_ref} plan {'approved' if payload.approved else 'sent back'}",
            message=payload.notes or ("You can start the work." if payload.approved else "The plan needs revising."),
            category="capa_plan_approval",
            subject_ref=capa.capa_ref,
        )

    db.commit()
    db.refresh(capa)
    return _detail(db, capa)


# ══════════════════════════════════════════════════════════════════════════════
# 05 ASSIGN
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/{capa_id}/assign", response_model=CapaDetail)
def assign_capa(
    capa_id: int,
    payload: CapaAssign,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 05. The owner is notified — personally, not by broadcast.

    The document's owner row reads "whoever is assigned — worker, supervisor or
    manager", so any active employee in the organisation may hold an action.
    """
    require_role(current_user.role, ALL_ELEVATED_ROLES, "assign a corrective action")
    capa = _get(db, capa_id, current_user)
    _require_unlocked(capa)

    exists = db.execute(
        text("SELECT id FROM employees WHERE id = :id AND organisation_id = :org_id"),
        {"id": payload.responsible_person_id, "org_id": capa.organisation_id},
    ).scalar()
    if not exists:
        raise HTTPException(status_code=404, detail="No such employee")

    capa.responsible_person_id = payload.responsible_person_id
    capa.assigned_by = employee_id_for(db, current_user.user_id)
    capa.assigned_at = datetime.utcnow()
    # Reassigning resets the chase: the new owner has not been nudged yet.
    capa.escalation_level = 0
    _notify_assignment(db, capa)

    db.commit()
    db.refresh(capa)
    return _detail(db, capa)


# ══════════════════════════════════════════════════════════════════════════════
# 06 DO
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/{capa_id}/start", response_model=CapaDetail)
def start_capa(
    capa_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 06. Work begins.

    Blocked where the plan needed manager approval and has not had it — that is
    the point of approving a plan for a High or Critical action.
    """
    capa = _get(db, capa_id, current_user)
    _require_unlocked(capa)
    _require_owner_or_elevated(db, capa, current_user, "start this action")

    if not (capa.success_criteria or "").strip():
        raise HTTPException(
            status_code=400,
            detail="Plan the action first — success criteria are required before work starts.",
        )
    if lc.requires_plan_approval(capa.priority_band) and not capa.plan_approved_at:
        raise HTTPException(
            status_code=400,
            detail=(
                f"This is a {capa.priority_band} priority action — a manager must approve "
                "the plan and its due date before work starts."
            ),
        )

    capa.status = lc.IN_PROGRESS
    capa.started_at = capa.started_at or datetime.utcnow()
    db.commit()
    db.refresh(capa)
    return _detail(db, capa)


@router.post("/{capa_id}/progress", response_model=CapaDetail)
def add_progress(
    capa_id: int,
    payload: CapaProgress,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 06. "Long-running actions need interim notes."

    Also what the 75% reminder reads: the nudge only fires where no progress has
    been recorded, so an owner who is visibly working is not pestered.
    """
    capa = _get(db, capa_id, current_user)
    _require_unlocked(capa)
    _require_owner_or_elevated(db, capa, current_user, "post progress on this action")

    db.add(CapaProgressNote(
        organisation_id=capa.organisation_id,
        capa_id=capa.id,
        note=payload.note,
        percent_complete=payload.percent_complete,
        author_id=employee_id_for(db, current_user.user_id),
    ))
    if capa.status == lc.OPEN:
        capa.status = lc.IN_PROGRESS
        capa.started_at = capa.started_at or datetime.utcnow()

    db.commit()
    db.refresh(capa)
    return _detail(db, capa)


@router.get("/{capa_id}/progress")
def list_progress(
    capa_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    capa = _get(db, capa_id, current_user)
    rows = (
        db.query(CapaProgressNote)
        .filter(CapaProgressNote.capa_id == capa.id)
        .order_by(CapaProgressNote.id.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "note": r.note,
            "percent_complete": r.percent_complete,
            "author_id": r.author_id,
            "author_name": _employee_name(db, r.author_id, capa.organisation_id),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.post("/{capa_id}/interim-check", response_model=CapaDetail)
def interim_check(
    capa_id: int,
    payload: CapaInterimCheck,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 06, the 50% gate: "When half the time has elapsed the Supervisor must
    confirm progress is real."

    One of the four points the document says cannot be bypassed, so evidence
    submission refuses until it has happened. The owner cannot perform it — a
    self-certified halfway check is not a check.
    """
    require_role(current_user.role, ALL_ELEVATED_ROLES, "run the interim check")
    capa = _get(db, capa_id, current_user)
    _require_unlocked(capa)

    if _is_owner(db, capa, current_user):
        raise HTTPException(
            status_code=403,
            detail="The action owner cannot confirm their own progress — this check is the supervisor's.",
        )

    capa.interim_check_by = employee_id_for(db, current_user.user_id)
    capa.interim_check_at = datetime.utcnow()
    capa.interim_check_notes = payload.notes

    if not payload.progress_is_real and capa.responsible_person_id:
        capa_notify.notify(
            db,
            org_id=capa.organisation_id,
            employee_id=capa.responsible_person_id,
            title=f"{capa.capa_ref} — halfway check failed",
            message=payload.notes or "Your supervisor could not see real progress at the halfway point.",
            category="capa_interim_check",
            subject_ref=capa.capa_ref,
            type_="warning",
        )

    db.commit()
    db.refresh(capa)
    return _detail(db, capa)


# ══════════════════════════════════════════════════════════════════════════════
# 07 EVIDENCE
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/{capa_id}/evidence/upload")
async def upload_evidence_file(
    capa_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Store the file, return the URL to attach with POST /evidence.

    Two calls rather than one multipart endpoint because a piece of evidence is
    not always a file — an inspection confirmation may be a reference and a date
    — and because the app uploads while the user is still typing the description.
    """
    capa = _get(db, capa_id, current_user)
    _require_unlocked(capa)
    _require_owner_or_elevated(db, capa, current_user, "attach evidence to this action")

    content = await file.read()
    try:
        url = media_storage.save_image(
            content,
            file.filename,
            file.content_type,
            subdir="capa",
            allowed_types=media_storage.EVIDENCE_CONTENT_TYPES,
        )
    except media_storage.MediaRejected as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"file_url": url}


@router.post("/{capa_id}/evidence", response_model=CapaDetail)
def add_evidence(
    capa_id: int,
    payload: CapaEvidenceCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 07. "Rejects the upload if the evidence type is wrong for that action
    type, or if it is dated before the action was raised."

    Rejected evidence is stored with its reason rather than discarded. The owner
    needs to see what was refused and why, and a pattern of rejections on one
    action is itself worth seeing.
    """
    capa = _get(db, capa_id, current_user)
    _require_unlocked(capa)
    _require_owner_or_elevated(db, capa, current_user, "attach evidence to this action")

    if not (capa.action_category or "").strip():
        raise HTTPException(
            status_code=400,
            detail="Plan the action first — the action category decides which evidence is valid.",
        )

    verdict = lc.validate_evidence(
        evidence_type=payload.evidence_type,
        evidence_date=payload.evidence_date,
        action_category=capa.action_category,
        capa_created_at=capa.created_at,
    )

    db.add(CapaEvidence(
        organisation_id=capa.organisation_id,
        capa_id=capa.id,
        evidence_type=(payload.evidence_type or "").strip().lower(),
        file_url=payload.file_url,
        description=payload.description,
        evidence_date=payload.evidence_date,
        uploaded_by=employee_id_for(db, current_user.user_id),
        uploaded_at=datetime.utcnow(),
        validation_result="accepted" if verdict.accepted else "rejected",
        rejection_reason=verdict.reason,
    ))
    db.commit()
    db.refresh(capa)

    if not verdict.accepted:
        raise HTTPException(status_code=400, detail=verdict.reason)
    return _detail(db, capa)


@router.post("/{capa_id}/submit", response_model=CapaDetail)
def submit_for_closure(
    capa_id: int,
    payload: CapaSubmit,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 07 -> 08. The owner marks the work done and hands it to validation.

    This is where the old one-click `complete` used to close the action and
    advance the parent record. It now moves to PENDING REVIEW at best, and only
    when the halfway check has been done and evidence exists to review.
    """
    capa = _get(db, capa_id, current_user)
    _require_unlocked(capa)
    _require_owner_or_elevated(db, capa, current_user, "submit this action")

    if not capa.interim_check_at:
        raise HTTPException(
            status_code=400,
            detail=(
                "The Supervisor's halfway check has not been done. It cannot be "
                "skipped — confirm progress first, then submit."
            ),
        )

    accepted = [
        e for e in _evidence_rows(db, capa.id)
        if (e.validation_result or "") != "rejected"
    ]
    if not accepted:
        raise HTTPException(
            status_code=400,
            detail="Attach at least one accepted piece of evidence before submitting.",
        )

    now = datetime.utcnow()
    capa.status = lc.PENDING_REVIEW
    capa.evidence_submitted_at = now
    capa.evidence_submitted_by = employee_id_for(db, current_user.user_id)
    checks = _closure_validation(db, capa)
    capa.closure_checks_json = checks.as_json()

    if payload.notes:
        db.add(CapaProgressNote(
            organisation_id=capa.organisation_id,
            capa_id=capa.id,
            note=payload.notes,
            percent_complete=100,
            author_id=capa.evidence_submitted_by,
        ))

    # The reviewer is anyone elevated other than the owner; the supervisor line
    # is the natural first call.
    reviewer = capa_notify.supervisor_of(db, capa.responsible_person_id)
    capa_notify.notify(
        db,
        org_id=capa.organisation_id,
        employee_id=reviewer,
        title=f"{capa.capa_ref} needs independent review",
        message=(
            f"{capa.description}\nEvidence submitted. Confirm the control is physically "
            "in place — the owner cannot sign off their own action."
        ),
        category="capa_review_due",
        subject_ref=capa.capa_ref,
    )

    db.commit()
    db.refresh(capa)
    return _detail(db, capa)


# ══════════════════════════════════════════════════════════════════════════════
# 08 CLOSURE VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/{capa_id}/closure-checks")
def closure_checks(
    capa_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """The three gates, run live. "The system, not a person, decides whether they
    pass" — so this is a read, and nothing here can be overridden."""
    capa = _get(db, capa_id, current_user)
    checks = _closure_validation(db, capa)
    return {
        "capa_ref": capa.capa_ref,
        "passed": checks.passed,
        "checks": checks.as_json(),
        "may_be_approved": checks.passed and not lc.is_terminal(capa.status),
    }


@router.post("/{capa_id}/independent-review", response_model=CapaDetail)
def independent_review(
    capa_id: int,
    payload: CapaIndependentReview,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 08, CHECK 3: "Someone other than the person who did the work must
    confirm it. An owner cannot sign off their own action."

    Enforced here and again in the closure checks, because the reviewer id is
    stored and the check re-reads it — a reassignment that made the reviewer the
    owner would otherwise leave a stale pass in place.
    """
    require_role(
        current_user.role,
        ALL_ELEVATED_ROLES | AUDITOR_ROLES,
        "independently review a corrective action",
    )
    capa = _get(db, capa_id, current_user)
    _require_unlocked(capa)

    if _is_owner(db, capa, current_user):
        raise HTTPException(
            status_code=403,
            detail="An owner cannot sign off their own action. The reviewer must be someone else.",
        )
    if not capa.evidence_submitted_at:
        raise HTTPException(status_code=400, detail="No evidence has been submitted to review.")

    now = datetime.utcnow()
    capa.independent_review_by = employee_id_for(db, current_user.user_id)
    capa.independent_review_at = now
    capa.independent_review_result = "confirmed" if payload.confirmed else "rejected"
    capa.independent_review_notes = payload.notes

    checks = _closure_validation(db, capa)
    capa.closure_checks_json = checks.as_json()

    if payload.confirmed and checks.passed:
        capa.status = lc.PENDING_APPROVAL
        capa_notify.notify_many(
            db,
            capa_notify.safety_managers(db, capa.organisation_id),
            org_id=capa.organisation_id,
            title=f"{capa.capa_ref} ready for closure approval",
            message=f"All three closure checks passed.\n{capa.description}",
            category="capa_approval_due",
            subject_ref=capa.capa_ref,
        )
    else:
        # Back to the owner to correct and resubmit — the document's step 09
        # owner row.
        capa.status = lc.IN_PROGRESS
        if capa.responsible_person_id:
            capa_notify.notify(
                db,
                org_id=capa.organisation_id,
                employee_id=capa.responsible_person_id,
                title=f"{capa.capa_ref} — evidence rejected",
                message=(payload.notes or "The reviewer could not confirm the control is in place.")
                + "\nCorrect it and resubmit.",
                category="capa_evidence_rejected",
                subject_ref=capa.capa_ref,
                type_="warning",
            )

    db.commit()
    db.refresh(capa)
    return _detail(db, capa)


# ══════════════════════════════════════════════════════════════════════════════
# 10 APPROVAL & ARCHIVE
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/{capa_id}/approve-closure", response_model=CapaDetail)
def approve_closure(
    capa_id: int,
    payload: CapaApproveClosure,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 10, the final gate. "Only this role can close an action."

    The three checks are re-run here rather than trusted from the stored result:
    evidence can be added, and an owner can be changed, between the review and
    the approval. A gate that reads a cached verdict is not a gate.
    """
    require_role(current_user.role, MANAGER_ROLES, "approve a CAPA closure")
    capa = _get(db, capa_id, current_user)

    if lc.is_terminal(capa.status):
        raise HTTPException(status_code=400, detail=f"{capa.capa_ref} is already closed.")

    checks = _closure_validation(db, capa)
    capa.closure_checks_json = checks.as_json()
    if not checks.passed:
        db.commit()
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Closure blocked — the three checks must pass first.",
                "failures": checks.failures(),
                "checks": checks.as_json(),
            },
        )

    if not payload.approved:
        capa.status = lc.IN_PROGRESS
        db.commit()
        db.refresh(capa)
        return _detail(db, capa)

    now = datetime.utcnow()
    capa.status = lc.CLOSED
    capa.closed_by = employee_id_for(db, current_user.user_id)
    capa.closed_at = now
    capa.closure_notes = payload.closure_notes
    capa.lesson_learned = payload.lesson_learned
    if payload.effectiveness_rating is not None:
        capa.effectiveness_rating = payload.effectiveness_rating
    capa.is_locked = 1

    # Step 09 is scheduled from closure — see capa_lifecycle.review_schedule for
    # why the reviews come after rather than before.
    for point, due_at in lc.review_schedule(now):
        db.add(CapaEffectivenessReview(
            organisation_id=capa.organisation_id,
            capa_id=capa.id,
            review_point=point,
            due_at=due_at,
            result="pending",
        ))

    advanced = _advance_parent(db, capa)

    if capa.responsible_person_id:
        capa_notify.notify(
            db,
            org_id=capa.organisation_id,
            employee_id=capa.responsible_person_id,
            title=f"{capa.capa_ref} closed",
            message="Your action was approved and closed. Effectiveness reviews follow at 30, 60 and 90 days.",
            category="capa_closed",
            subject_ref=capa.capa_ref,
            type_="success",
        )

    db.commit()
    db.refresh(capa)
    out = _detail(db, capa)
    if advanced:
        out.next_action = f"Closed. Parent {capa.subject_family} advanced to '{advanced}'."
    return out


@router.post("/{capa_id}/reopen", response_model=CapaDetail)
def reopen_capa(
    capa_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Manual reopen. The automatic one lives in the effectiveness review."""
    require_role(current_user.role, MANAGER_ROLES, "reopen a corrective action")
    capa = _get(db, capa_id, current_user)
    if not lc.is_terminal(capa.status):
        raise HTTPException(status_code=400, detail="This action is not closed.")
    _reopen(db, capa, "A manager reopened this action.")
    db.commit()
    db.refresh(capa)
    return _detail(db, capa)


def _reopen(db: Session, capa: CapaAction, why: str) -> None:
    """Put a closed action back into IMPROVE, and its parent with it.

    The independent review is cleared deliberately. It attested to a control
    that has since been found wanting, so carrying it forward would let the
    action walk back to approval on a sign-off that is now known to be wrong —
    the same failure the incident-level verification loop already guards.
    """
    capa.status = lc.IN_PROGRESS
    capa.is_locked = 0
    capa.reopened_count = (capa.reopened_count or 0) + 1
    capa.closed_at = None
    capa.closed_by = None
    capa.independent_review_result = None
    capa.independent_review_by = None
    capa.independent_review_at = None
    capa.evidence_submitted_at = None
    # Reset the chase so the escalation chain runs again against the new work.
    capa.escalation_level = 0

    _return_parent_to_improve(db, capa)

    if capa.responsible_person_id:
        capa_notify.notify(
            db,
            org_id=capa.organisation_id,
            employee_id=capa.responsible_person_id,
            title=f"{capa.capa_ref} reopened",
            message=why,
            category="capa_reopened",
            subject_ref=capa.capa_ref,
            type_="warning",
        )


# ══════════════════════════════════════════════════════════════════════════════
# 09 EFFECTIVENESS REVIEWS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/{capa_id}/effectiveness-reviews", response_model=List[CapaEffectivenessReviewOut])
def list_reviews(
    capa_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    capa = _get(db, capa_id, current_user)
    return (
        db.query(CapaEffectivenessReview)
        .filter(CapaEffectivenessReview.capa_id == capa.id)
        .order_by(CapaEffectivenessReview.review_point)
        .all()
    )


@router.get("/reviews/due", response_model=List[CapaEffectivenessReviewOut])
def reviews_due(
    days_ahead: int = Query(0, ge=0, le=90),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """The safety team's queue of effectiveness checks."""
    require_role(current_user.role, ALL_READ_ROLES, "view effectiveness reviews")
    cutoff = datetime.utcnow() + timedelta(days=days_ahead)
    return (
        db.query(CapaEffectivenessReview)
        .filter(
            CapaEffectivenessReview.organisation_id == current_user.org_id,
            CapaEffectivenessReview.result == "pending",
            CapaEffectivenessReview.due_at <= cutoff,
        )
        .order_by(CapaEffectivenessReview.due_at)
        .all()
    )


@router.post("/reviews/{review_id}", response_model=CapaDetail)
def submit_review(
    review_id: int,
    payload: CapaEffectivenessReviewSubmit,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Step 09. "Any failure reopens the action."

    The three questions are stored as three answers, not one verdict, because
    "the control is still in place but it recurred" is a different finding from
    "someone removed the control" and the systemic review needs to tell them
    apart.
    """
    require_role(current_user.role, ALL_ELEVATED_ROLES, "record an effectiveness review")
    review = (
        db.query(CapaEffectivenessReview)
        .filter(
            CapaEffectivenessReview.id == review_id,
            CapaEffectivenessReview.organisation_id == current_user.org_id,
        )
        .first()
    )
    if not review:
        raise HTTPException(status_code=404, detail="Effectiveness review not found")
    if review.result != "pending":
        raise HTTPException(status_code=400, detail="This review has already been recorded.")

    capa = db.query(CapaAction).filter(CapaAction.id == review.capa_id).first()
    if not capa:
        raise HTTPException(status_code=404, detail="The action this review belongs to is missing")

    review.has_recurred = int(bool(payload.has_recurred))
    review.control_in_place = int(bool(payload.control_in_place))
    review.root_cause_addressed = int(bool(payload.root_cause_addressed))
    review.notes = payload.notes
    review.reviewed_by = employee_id_for(db, current_user.user_id)
    review.reviewed_at = datetime.utcnow()
    review.result = lc.review_verdict(
        payload.has_recurred, payload.control_in_place, payload.root_cause_addressed
    )

    if review.result == "failed":
        review.triggered_reopen = 1
        # Cancel the later checks. They were scheduled against a fix that has
        # just been shown not to hold, so answering them would be meaningless —
        # the reopened action schedules its own on the next closure.
        db.query(CapaEffectivenessReview).filter(
            CapaEffectivenessReview.capa_id == capa.id,
            CapaEffectivenessReview.result == "pending",
            CapaEffectivenessReview.id != review.id,
        ).update({"result": "cancelled"}, synchronize_session=False)

        _reopen(
            db, capa,
            f"The {review.review_point}-day effectiveness review failed: "
            + (payload.notes or "the fix did not hold."),
        )

    db.commit()
    db.refresh(capa)
    return _detail(db, capa)


# ══════════════════════════════════════════════════════════════════════════════
# Reads
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/my-actions")
def my_actions(
    mine: Optional[bool] = Query(None, description="Defaults to true for everyone except managers"),
    include_closed: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """The owner's list. Any role can own an action, so no role gate here."""
    emp_id = employee_id_for(db, current_user.user_id)
    only_mine = mine if mine is not None else not role_matches(current_user.role, MANAGER_ROLES)

    q = db.query(CapaAction).filter(CapaAction.organisation_id == current_user.org_id)
    if not include_closed:
        q = q.filter(func.lower(func.coalesce(CapaAction.status, "")).notin_(list(lc.TERMINAL)))
    if only_mine:
        q = q.filter(CapaAction.responsible_person_id == emp_id)

    rows = q.order_by(CapaAction.due_date.is_(None), CapaAction.due_date).limit(200).all()
    return [_summary(db, c) for c in rows]


def _summary(db: Session, capa: CapaAction) -> dict:
    stage = lc.describe(capa)
    return {
        "id": capa.id,
        "capa_ref": capa.capa_ref,
        "description": capa.description,
        # incident_id is the reliable column for incident-raised CAPAs — older
        # rows (raised before migration 056) never got subject_family/subject_id
        # backfilled, so that pair alone under-reports which CAPAs trace to an
        # incident. incident_id stays populated for all of them.
        "incident_id": capa.incident_id,
        "subject_family": capa.subject_family,
        "subject_id": capa.subject_id,
        "status": capa.status,
        "step": stage["step"],
        "step_label": stage["step_label"],
        "priority_band": capa.priority_band,
        "capa_type": capa.capa_type,
        "due_date": capa.due_date.isoformat() if capa.due_date else None,
        "elapsed_percent": stage["elapsed_percent"],
        "is_overdue": stage["is_overdue"],
        "escalation_level": stage["escalation_level"],
        "responsible_person_id": capa.responsible_person_id,
        "responsible_person_name": _employee_name(db, capa.responsible_person_id, capa.organisation_id),
        "systemic_flag": bool(capa.systemic_flag),
        "reopened_count": capa.reopened_count or 0,
    }


@router.get("/ageing")
def ageing_report(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """"Receives the ageing report of everything open" — the manager's step 05.

    Bucketed by elapsed proportion of the deadline rather than by age in days,
    for the same reason the escalation chain is: a 24-hour action four hours
    late and a 90-day action four hours late are not the same problem.
    """
    require_role(current_user.role, ALL_READ_ROLES, "view the CAPA ageing report")
    rows = (
        db.query(CapaAction)
        .filter(CapaAction.organisation_id == current_user.org_id)
        .filter(func.lower(func.coalesce(CapaAction.status, "")).notin_(list(lc.TERMINAL)))
        .all()
    )

    buckets = {"on_track": [], "approaching": [], "overdue": [], "critical_overdue": [], "no_deadline": []}
    for c in rows:
        pct = lc.elapsed_percent(c.created_at, c.due_date)
        if pct is None:
            buckets["no_deadline"].append(_summary(db, c))
        elif pct >= 110:
            buckets["critical_overdue"].append(_summary(db, c))
        elif pct >= 100:
            buckets["overdue"].append(_summary(db, c))
        elif pct >= 75:
            buckets["approaching"].append(_summary(db, c))
        else:
            buckets["on_track"].append(_summary(db, c))

    return {
        "total_open": len(rows),
        "counts": {k: len(v) for k, v in buckets.items()},
        "buckets": buckets,
        "systemic_flagged": sum(1 for c in rows if c.systemic_flag),
    }


@router.get("/queue")
def stage_queue(
    stage: str = Query(..., description="interim | review | approval | unassigned"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """What this role is holding up, by lifecycle stage.

    Four of the ten steps are somebody's inbox rather than the owner's work, and
    each was reachable only by knowing an action's id: the halfway check, the
    independent review, the closure approval, and naming an owner in the first
    place. `my-actions` cannot answer these — it is the owner's list, and none of
    these four are done by the owner.

    Read-only and role-gated at the read level only. Each write endpoint applies
    its own rule (the owner may not check their own progress, may not review
    their own evidence, and only the Safety Manager approves a closure), so a
    supervisor seeing an action here does not mean they may act on it — the
    screen shows why when the write refuses.
    """
    require_role(current_user.role, ALL_READ_ROLES, "view the CAPA queues")

    q = db.query(CapaAction).filter(
        CapaAction.organisation_id == current_user.org_id,
        func.lower(func.coalesce(CapaAction.status, "")).notin_(list(lc.TERMINAL)),
    )

    key = (stage or "").strip().lower()
    if key == "interim":
        # Started, halfway check not yet done. Deliberately not filtered on the
        # 50% mark: an owner who finishes early is blocked at submit by the same
        # missing check, and a supervisor who cannot see the action until half
        # the window has gone cannot clear it for them.
        q = q.filter(
            CapaAction.interim_check_at.is_(None),
            CapaAction.responsible_person_id.isnot(None),
            func.lower(func.coalesce(CapaAction.status, "")).in_(
                [lc.IN_PROGRESS.lower(), lc.EVIDENCE_SUBMITTED.lower()]
            ),
        )
    elif key == "review":
        q = q.filter(func.lower(func.coalesce(CapaAction.status, "")) == lc.PENDING_REVIEW.lower())
    elif key == "approval":
        q = q.filter(func.lower(func.coalesce(CapaAction.status, "")) == lc.PENDING_APPROVAL.lower())
    elif key == "unassigned":
        q = q.filter(CapaAction.responsible_person_id.is_(None))
    else:
        raise HTTPException(
            status_code=400,
            detail="stage must be one of: interim, review, approval, unassigned",
        )

    rows = q.order_by(CapaAction.due_date.is_(None), CapaAction.due_date).limit(200).all()
    return [_summary(db, c) for c in rows]


@router.get("/assignable-owners")
def assignable_owners(
    include_workers: bool = Query(
        False, description="Widen past the accountable line to the whole workforce",
    ),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Who step 05 may hand an action to.

    The same list the incident and report families already offer, from
    `app.services.capa_owners` — a second query for "who may own a CAPA" would
    disagree with the first the day a role is added. Note this is narrower than
    what `assign` accepts: the write takes any employee in the organisation,
    because the lifecycle document's owner row reads "worker, supervisor or
    manager". The picker leads with the accountable line rather than the whole
    payroll.
    """
    require_role(current_user.role, ALL_READ_ROLES, "list assignable owners")
    return capa_owners.assignable_owners(db, current_user.org_id, include_workers)


@router.get("/all")
def list_all_capa(
    page: int = Query(1, ge=1),
    pageSize: int = Query(25, ge=1, le=200),
    overdue_only: bool = Query(False),
    unassigned_only: bool = Query(False, description="Only actions with no owner yet — step 05 is owed."),
    include_closed: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Paginated CAPA list backing the dashboard's "View All Actions" /
    "View All Overdue CAPA" links — every action for this org, not just the
    top-N preview shown on the dashboard.

    overdue_only mirrors is_overdue in capa_lifecycle.describe(): due date has
    passed and the action hasn't reached a terminal status. Real data never
    sets a literal status of "Overdue" — the lifecycle here treats lateness as
    a property of the due date, not a state — so filtering on that string
    matched zero rows for anything but the original demo dataset.
    """
    q = db.query(CapaAction).filter(CapaAction.organisation_id == current_user.org_id)
    if overdue_only:
        today = date.today()
        q = q.filter(
            CapaAction.due_date.isnot(None),
            CapaAction.due_date < today,
            func.lower(func.coalesce(CapaAction.status, "")).notin_(list(lc.TERMINAL)),
        )
    elif not include_closed:
        q = q.filter(func.lower(func.coalesce(CapaAction.status, "")).notin_(list(lc.TERMINAL)))
    if unassigned_only:
        # An audit raises its actions deliberately unassigned — the auditor finds
        # the non-conformance, the Safety Manager names who fixes it. Closed rows
        # are never in this queue whatever `include_closed` says: an action that
        # ended without an owner is history, not work.
        q = q.filter(
            CapaAction.responsible_person_id.is_(None),
            func.lower(func.coalesce(CapaAction.status, "")).notin_(list(lc.TERMINAL)),
        )

    total = q.count()
    rows = (
        q.order_by(CapaAction.due_date.is_(None), CapaAction.due_date)
        .offset((page - 1) * pageSize)
        .limit(pageSize)
        .all()
    )
    return {
        "data": [_summary(db, c) for c in rows],
        "total": total,
        "page": page,
        "pageSize": pageSize,
        "totalPages": math.ceil(total / pageSize) if total else 0,
    }


@router.get("/{capa_id}", response_model=CapaDetail)
def get_capa(
    capa_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    return _detail(db, _get(db, capa_id, current_user))
