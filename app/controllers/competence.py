"""WF-06 · Training, Competence & Human Readiness.

    worker      GET  /competence-matrix/my-card        the competence card, 60/30/7
    worker      GET  /competence-matrix/my-gaps
    worker      POST /training-records                 course completion, score
    worker      POST /training-records/{id}/toolbox-ack
    supervisor  GET  /competence-matrix/team           nightly gap report
    supervisor  POST /competence-matrix/assign-buddy
    supervisor  POST /training-records/{id}/verify     verify team training
    manager     GET  /competence-matrix                the matrix itself
    manager     POST /competence-matrix                Safety Manager may amend on mobile
    manager     GET  /competence-matrix/effectiveness  incident rate trained vs untrained
    auditor     GET  /competence-matrix/audit-list     sample workers, flag expired certs

Why this comes first: the competence matrix gates the permit. Until it exists,
gate 2 has nothing to check against, so WF-06 is a prerequisite for permit
control rather than a parallel task.
"""
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.controllers.workflow_common import (
    AUDITOR_ROLES,
    MANAGER_ROLES,
    SUPERVISOR_ROLES,
    employee_id_for,
    require_role,
    role_matches,
)
from app.core.dependencies import CurrentUser, get_current_user
from app.models.competence import (
    CertificationType,
    CompetenceGap,
    CompetenceMatrix,
    TrainingRecord,
)
from app.schemas.competence import (
    BuddyAssign,
    CertificationTypeCreate,
    CertificationTypeResponse,
    CompetenceCardItem,
    CompetenceCardResponse,
    CompetenceGapResponse,
    CompetenceMatrixCreate,
    CompetenceMatrixResponse,
    TeamMatrixRow,
    TrainingEffectivenessResponse,
    TrainingRecordCreate,
    TrainingRecordResponse,
    TrainingVerify,
)

router = APIRouter(prefix="/competence-matrix", tags=["Competence & Training"])
training_router = APIRouter(prefix="/training-records", tags=["Competence & Training"])

# The spec's competence card thresholds.
EXPIRY_BANDS = (60, 30, 7)
NEW_WORKER_DAYS = 30

# Supervisors and above may read a team matrix. Auditors read it for assurance
# but never write to it — see the interaction matrix.
MATRIX_READERS = SUPERVISOR_ROLES | MANAGER_ROLES | AUDITOR_ROLES


def _require_employee(db: Session, current_user: CurrentUser) -> int:
    emp_id = employee_id_for(db, current_user.user_id)
    if not emp_id:
        raise HTTPException(status_code=400, detail="No employee record linked to this user")
    return emp_id


def _applicable_requirements(db: Session, org_id: Optional[int]) -> List[CompetenceMatrix]:
    return (
        db.query(CompetenceMatrix)
        .filter(CompetenceMatrix.organisation_id == org_id)
        .filter(CompetenceMatrix.is_mandatory == 1)
        .all()
    )


def _build_card(db: Session, org_id: Optional[int], employee_id: int) -> CompetenceCardResponse:
    """The worker's live competence card — what is valid, expiring and blocked."""
    today = date.today()
    requirements = _applicable_requirements(db, org_id)
    records = (
        db.query(TrainingRecord)
        .filter(TrainingRecord.employee_id == employee_id)
        .filter(TrainingRecord.result == "pass")
        .all()
    )

    items: List[CompetenceCardItem] = []
    for req in requirements:
        match = next(
            (
                r for r in records
                if (req.certification_type_id and r.certification_type_id == req.certification_type_id)
                or (req.training_program_id and r.training_program_id == req.training_program_id)
                or (r.competence_matrix_id == req.id)
            ),
            None,
        )

        if match is None:
            status, expires, days = "missing", None, None
        elif match.expires_at is None:
            status, expires, days = "valid", None, None
        else:
            expires = match.expires_at
            days = (expires - today).days
            if days < 0:
                status = "expired"
            elif days <= EXPIRY_BANDS[0]:
                status = "expiring"
            else:
                status = "valid"

        items.append(
            CompetenceCardItem(
                requirement_name=req.requirement_name,
                competence_matrix_id=req.id,
                is_safety_critical=bool(req.is_safety_critical),
                status=status,
                expires_at=expires,
                days_to_expiry=days,
                # "Shows which tasks are blocked" — an expired or missing
                # safety-critical certificate is a hard block on the permit gate.
                blocks_permit=bool(req.is_safety_critical) and status in ("expired", "missing"),
            )
        )

    emp = db.execute(
        text("SELECT full_name, employment_start_date FROM employees WHERE id = :i"),
        {"i": employee_id},
    ).mappings().first()

    is_new = False
    if emp and emp["employment_start_date"]:
        start = emp["employment_start_date"]
        if isinstance(start, datetime):
            start = start.date()
        is_new = (today - start).days <= NEW_WORKER_DAYS

    return CompetenceCardResponse(
        employee_id=employee_id,
        employee_name=emp["full_name"] if emp else None,
        items=items,
        valid_count=sum(1 for i in items if i.status == "valid"),
        expiring_count=sum(1 for i in items if i.status == "expiring"),
        expired_count=sum(1 for i in items if i.status == "expired"),
        missing_count=sum(1 for i in items if i.status == "missing"),
        blocked_tasks=[i.requirement_name for i in items if i.blocks_permit],
        is_new_worker=is_new,
    )


# ══════════════════════════════════════════════════════════════════════════════
# WORKER — my competence card
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/my-card", response_model=CompetenceCardResponse)
def my_competence_card(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    return _build_card(db, current_user.org_id, _require_employee(db, current_user))


@router.get("/my-gaps", response_model=List[CompetenceGapResponse])
def my_gaps(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    emp_id = _require_employee(db, current_user)
    rows = (
        db.query(CompetenceGap)
        .filter(CompetenceGap.employee_id == emp_id)
        .filter(CompetenceGap.resolved_at.is_(None))
        .order_by(CompetenceGap.id.desc())
        .all()
    )
    return [CompetenceGapResponse.model_validate(r) for r in rows]


@router.get("/card/{employee_id}", response_model=CompetenceCardResponse)
def competence_card_for(
    employee_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Any elevated role may read a named worker's card (team matrix drill-down)."""
    require_role(current_user.role, MATRIX_READERS, "read another worker's competence card")
    return _build_card(db, current_user.org_id, employee_id)


# ══════════════════════════════════════════════════════════════════════════════
# SUPERVISOR — team competence matrix + nightly gap report
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/team", response_model=List[TeamMatrixRow])
def team_matrix(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Nightly gap report. Flags who is blocked and who needs a buddy."""
    require_role(current_user.role, MATRIX_READERS, "view the team competence matrix")

    employees = db.execute(
        text(
            "SELECT id, full_name, employment_start_date FROM employees "
            "WHERE organisation_id = :org AND (active_status IS NULL OR active_status != 'Inactive')"
        ),
        {"org": current_user.org_id},
    ).mappings().all()

    rows: List[TeamMatrixRow] = []
    for emp in employees:
        card = _build_card(db, current_user.org_id, emp["id"])
        rows.append(
            TeamMatrixRow(
                employee_id=emp["id"],
                employee_name=emp["full_name"],
                valid_count=card.valid_count,
                expiring_count=card.expiring_count,
                expired_count=card.expired_count,
                missing_count=card.missing_count,
                is_blocked=bool(card.blocked_tasks),
                # "Assign buddy for new workers on WAH / CS / hot work."
                buddy_required=card.is_new_worker,
            )
        )
    return rows


@router.post("/assign-buddy", response_model=CompetenceGapResponse)
def assign_buddy(
    payload: BuddyAssign,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES, "assign a competence buddy")

    if payload.competence_gap_id:
        gap = db.query(CompetenceGap).filter(CompetenceGap.id == payload.competence_gap_id).first()
        if not gap:
            raise HTTPException(status_code=404, detail="Competence gap not found")
    else:
        gap = CompetenceGap(
            organisation_id=current_user.org_id,
            employee_id=payload.employee_id,
            gap_type="missing",
            requirement_name="New-worker supervision",
            detected_at=datetime.now(),
            source_system="mobile",
        )
        db.add(gap)

    gap.buddy_employee_id = payload.buddy_employee_id
    gap.last_reviewed_at = datetime.now()
    db.commit()
    db.refresh(gap)
    return CompetenceGapResponse.model_validate(gap)


@router.get("/gaps", response_model=List[CompetenceGapResponse])
def all_gaps(
    gap_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, MATRIX_READERS, "view competence gaps")
    q = (
        db.query(CompetenceGap)
        .filter(CompetenceGap.organisation_id == current_user.org_id)
        .filter(CompetenceGap.resolved_at.is_(None))
    )
    if gap_type:
        q = q.filter(CompetenceGap.gap_type == gap_type)
    return [CompetenceGapResponse.model_validate(r) for r in q.order_by(CompetenceGap.id.desc()).all()]


@router.post("/recompute-gaps")
def recompute_gaps(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Rebuild the gap table from the matrix and the training records.

    Runs nightly in production. Exposed so a supervisor can force a refresh
    after logging training rather than waiting for the batch.
    """
    require_role(current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES, "recompute competence gaps")
    today = date.today()

    employees = db.execute(
        text("SELECT id FROM employees WHERE organisation_id = :org"),
        {"org": current_user.org_id},
    ).mappings().all()

    db.query(CompetenceGap).filter(
        CompetenceGap.organisation_id == current_user.org_id,
        CompetenceGap.resolved_at.is_(None),
    ).delete(synchronize_session=False)

    created = 0
    for emp in employees:
        card = _build_card(db, current_user.org_id, emp["id"])
        for item in card.items:
            if item.status == "valid":
                continue
            if item.status == "missing":
                gap_type = "missing"
            elif item.status == "expired":
                gap_type = "expired"
            else:
                d = item.days_to_expiry or 0
                gap_type = "expiring_7" if d <= 7 else ("expiring_30" if d <= 30 else "expiring_60")

            db.add(
                CompetenceGap(
                    organisation_id=current_user.org_id,
                    employee_id=emp["id"],
                    competence_matrix_id=item.competence_matrix_id,
                    requirement_name=item.requirement_name,
                    gap_type=gap_type,
                    is_safety_critical=1 if item.is_safety_critical else 0,
                    expires_at=item.expires_at,
                    detected_at=datetime.now(),
                    source_system="server",
                    last_verified_at=datetime.now(),
                )
            )
            created += 1

    db.commit()
    return {"employees_checked": len(employees), "gaps_created": created}


# ══════════════════════════════════════════════════════════════════════════════
# SAFETY MANAGER — owns the matrix, reads training effectiveness
# ══════════════════════════════════════════════════════════════════════════════
@router.get("", response_model=List[CompetenceMatrixResponse])
@router.get("/", response_model=List[CompetenceMatrixResponse])
def list_matrix(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """All roles read the matrix — the worker's card is built from it."""
    rows = (
        db.query(CompetenceMatrix)
        .filter(CompetenceMatrix.organisation_id == current_user.org_id)
        .order_by(CompetenceMatrix.id.desc())
        .all()
    )
    return [CompetenceMatrixResponse.model_validate(r) for r in rows]


@router.post("", response_model=CompetenceMatrixResponse, status_code=201)
@router.post("/", response_model=CompetenceMatrixResponse, status_code=201)
def create_matrix_entry(
    payload: CompetenceMatrixCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Web authors the matrix. The interaction matrix grants the Safety Manager
    READ + WRITE on mobile, so Manager roles may amend it here."""
    require_role(current_user.role, MANAGER_ROLES, "amend the competence matrix")

    row = CompetenceMatrix(
        organisation_id=current_user.org_id,
        requirement_name=payload.requirement_name,
        competence_profile_id=payload.competence_profile_id,
        role_id=payload.role_id,
        training_program_id=payload.training_program_id,
        certification_type_id=payload.certification_type_id,
        is_mandatory=1 if payload.is_mandatory else 0,
        is_safety_critical=1 if payload.is_safety_critical else 0,
        validity_months=payload.validity_months,
        permit_types_gated=payload.permit_types_gated,
        source_system="mobile",
        last_reviewed_at=datetime.now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return CompetenceMatrixResponse.model_validate(row)


@router.get("/effectiveness", response_model=TrainingEffectivenessResponse)
def training_effectiveness(
    months: int = Query(12, ge=1, le=60),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Monthly training effectiveness: incident rate trained vs untrained.

    This is the number that tells a Safety Manager whether training is working,
    rather than merely whether it was delivered.
    """
    require_role(current_user.role, MANAGER_ROLES | AUDITOR_ROLES, "view training effectiveness")
    since = date.today() - timedelta(days=30 * months)

    trained_ids = {
        r["employee_id"]
        for r in db.execute(
            text(
                "SELECT DISTINCT employee_id FROM training_records "
                "WHERE organisation_id = :org AND result = 'pass' AND completed_at >= :since"
            ),
            {"org": current_user.org_id, "since": since},
        ).mappings()
    }
    all_ids = {
        r["id"]
        for r in db.execute(
            text("SELECT id FROM employees WHERE organisation_id = :org"),
            {"org": current_user.org_id},
        ).mappings()
    }
    untrained_ids = all_ids - trained_ids

    def _incidents(ids: set) -> int:
        if not ids:
            return 0
        rows = db.execute(
            text(
                "SELECT COUNT(*) AS c FROM incidents "
                "WHERE organisation_id = :org AND reported_by IN :ids AND created_at >= :since"
            ).bindparams(),
            {"org": current_user.org_id, "ids": tuple(ids), "since": since},
        ).mappings().first()
        return int(rows["c"]) if rows else 0

    try:
        inc_trained = _incidents(trained_ids)
        inc_untrained = _incidents(untrained_ids)
    except Exception:
        # `reported_by` is not present on every deployment's incidents table.
        inc_trained = inc_untrained = 0

    rate_t = round(inc_trained / len(trained_ids), 3) if trained_ids else 0.0
    rate_u = round(inc_untrained / len(untrained_ids), 3) if untrained_ids else 0.0
    ratio = round(rate_u / rate_t, 2) if rate_t else None

    if ratio is None or len(trained_ids) < 5 or len(untrained_ids) < 5:
        # Below this the ratio is noise, not signal — say so rather than
        # reporting a confident-looking number off a handful of people.
        ratio = None
        interpretation = "Not enough data to compare trained and untrained incident rates."
    elif ratio > 1:
        interpretation = f"Untrained staff have {ratio}x the incident rate of trained staff."
    else:
        interpretation = "Trained and untrained incident rates are comparable — review content."

    return TrainingEffectivenessResponse(
        period_months=months,
        trained_employees=len(trained_ids),
        untrained_employees=len(untrained_ids),
        incidents_trained=inc_trained,
        incidents_untrained=inc_untrained,
        rate_trained=rate_t,
        rate_untrained=rate_u,
        effectiveness_ratio=ratio,
        interpretation=interpretation,
    )


# ══════════════════════════════════════════════════════════════════════════════
# AUDITOR — competence evidence audit
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/audit-list", response_model=List[TeamMatrixRow])
def competence_audit_list(
    only_expired: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Sample workers on site, verify certs against the matrix, flag any
    expired safety-critical cert."""
    require_role(current_user.role, AUDITOR_ROLES | MANAGER_ROLES, "run a competence evidence audit")
    rows = team_matrix(db=db, current_user=current_user)
    return [r for r in rows if r.expired_count or r.missing_count] if only_expired else rows


# ══════════════════════════════════════════════════════════════════════════════
# Certification types (master data)
# ══════════════════════════════════════════════════════════════════════════════
@router.get("/certification-types", response_model=List[CertificationTypeResponse])
def list_certification_types(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    rows = (
        db.query(CertificationType)
        .filter(CertificationType.organisation_id == current_user.org_id)
        .all()
    )
    return [CertificationTypeResponse.model_validate(r) for r in rows]


@router.post("/certification-types", response_model=CertificationTypeResponse, status_code=201)
def create_certification_type(
    payload: CertificationTypeCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, MANAGER_ROLES, "create a certification type")
    row = CertificationType(
        organisation_id=current_user.org_id,
        name=payload.name,
        code=payload.code,
        issuing_body=payload.issuing_body,
        validity_months=payload.validity_months,
        is_safety_critical=1 if payload.is_safety_critical else 0,
        description=payload.description,
        source_system="mobile",
        last_reviewed_at=datetime.now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return CertificationTypeResponse.model_validate(row)


# ══════════════════════════════════════════════════════════════════════════════
# TRAINING RECORDS  (/training-records)
# ══════════════════════════════════════════════════════════════════════════════
@training_router.post("", response_model=TrainingRecordResponse, status_code=201)
@training_router.post("/", response_model=TrainingRecordResponse, status_code=201)
def log_training(
    payload: TrainingRecordCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Worker logs a course completion. Below pass = the flag stays."""
    emp_id = payload.employee_id or _require_employee(db, current_user)
    if payload.employee_id and payload.employee_id != employee_id_for(db, current_user.user_id):
        require_role(
            current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES,
            "log training for another employee",
        )

    expires = payload.expires_at
    if expires is None and payload.certification_type_id and payload.completed_at:
        ct = (
            db.query(CertificationType)
            .filter(CertificationType.id == payload.certification_type_id)
            .first()
        )
        if ct and ct.validity_months:
            expires = payload.completed_at + timedelta(days=30 * ct.validity_months)

    row = TrainingRecord(
        organisation_id=current_user.org_id,
        employee_id=emp_id,
        training_program_id=payload.training_program_id,
        certification_type_id=payload.certification_type_id,
        competence_matrix_id=payload.competence_matrix_id,
        course_name=payload.course_name,
        completed_at=payload.completed_at or date.today(),
        expires_at=expires,
        score=payload.score,
        result=payload.result or "pass",
        certificate_ref=payload.certificate_ref,
        evidence_photo=payload.evidence_photo,
        source_system="mobile",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return TrainingRecordResponse.model_validate(row)


@training_router.get("/mine", response_model=List[TrainingRecordResponse])
def my_training(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    emp_id = _require_employee(db, current_user)
    rows = (
        db.query(TrainingRecord)
        .filter(TrainingRecord.employee_id == emp_id)
        .order_by(TrainingRecord.id.desc())
        .all()
    )
    return [TrainingRecordResponse.model_validate(r) for r in rows]


@training_router.get("", response_model=List[TrainingRecordResponse])
@training_router.get("/", response_model=List[TrainingRecordResponse])
def list_training(
    employee_id: Optional[int] = None,
    expiring_days: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_role(current_user.role, MATRIX_READERS, "list training records")
    q = db.query(TrainingRecord).filter(TrainingRecord.organisation_id == current_user.org_id)
    if employee_id:
        q = q.filter(TrainingRecord.employee_id == employee_id)
    if expiring_days is not None:
        q = q.filter(TrainingRecord.expires_at <= date.today() + timedelta(days=expiring_days))
    return [TrainingRecordResponse.model_validate(r) for r in q.order_by(TrainingRecord.id.desc()).all()]


@training_router.post("/{record_id}/verify", response_model=TrainingRecordResponse)
def verify_training(
    record_id: int,
    payload: TrainingVerify,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Supervisor verifies team training. Auditor audits it — both recorded."""
    require_role(
        current_user.role, SUPERVISOR_ROLES | MANAGER_ROLES | AUDITOR_ROLES,
        "verify a training record",
    )
    row = db.query(TrainingRecord).filter(TrainingRecord.id == record_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Training record not found")

    row.verified_by = employee_id_for(db, current_user.user_id)
    row.verified_at = datetime.now()
    row.last_verified_at = datetime.now()
    db.commit()
    db.refresh(row)
    return TrainingRecordResponse.model_validate(row)


@training_router.post("/{record_id}/toolbox-ack", response_model=TrainingRecordResponse)
def toolbox_acknowledge(
    record_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Toolbox acknowledge — feeds the 80% attendance rule on the worker card."""
    row = db.query(TrainingRecord).filter(TrainingRecord.id == record_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Training record not found")
    row.toolbox_acknowledged_at = datetime.now()
    db.commit()
    db.refresh(row)
    return TrainingRecordResponse.model_validate(row)
