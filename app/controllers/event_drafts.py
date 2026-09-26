"""Stage 01 RECORD — capture now, submit when you have the details.

One controller for every event family. A draft is the record while it is at
stage 01: it is not triaged, not assigned, not counted, and not visible to
anyone but its author. Submitting is what starts the workflow — the draft is
handed to the family's own create endpoint, so the record that appears at stage
02 has been through exactly the same validation, station lookup and assessment
as one submitted directly.

Why a separate table rather than a `draft` status on the real tables: see
migration 055. Short version — `incidents` and friends are counted
unconditionally by the recurrence lookup behind the P1-P5 classification, the
SPS engine, contractor risk and the dashboards, so an unfinished form living
there would inflate the KPIs and change the computed severity of other records.
"""
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import CurrentUser, get_current_user
from app.models.event_draft import EventDraft
from app.schemas.event_draft import (
    EventDraftCreate,
    EventDraftResponse,
    EventDraftUpdate,
)
from app.services import workflow_stages

router = APIRouter(prefix="/drafts", tags=["Event Drafts"])


# ══════════════════════════════════════════════════════════════════════════════
# Family -> create path
#
# Imports are deferred to call time: every one of these modules imports models
# and services that in turn import this package, so resolving them at module
# scope deadlocks the import graph.
# ══════════════════════════════════════════════════════════════════════════════

def _submit_incident(db: Session, current_user: CurrentUser, payload: Dict[str, Any]):
    from app.controllers.incident_workflow import worker_report_incident
    from app.schemas.incident_workflow import WorkerIncidentReport

    return worker_report_incident(WorkerIncidentReport(**payload), db, current_user)


def _submit_via_report_router(module_path: str):
    """Adapter for the three factory-built families.

    `worker_report` is a closure inside build_workflow_router, so the factory
    attaches it to the router as `create_from_payload`.
    """
    def _submit(db: Session, current_user: CurrentUser, payload: Dict[str, Any]):
        import importlib

        mod = importlib.import_module(module_path)
        schema = mod.router.create_schema
        return mod.router.create_from_payload(schema(**payload), db, current_user)

    return _submit


def _submit_hazard_register(db: Session, current_user: CurrentUser, payload: Dict[str, Any]):
    from app.controllers.hazard_register import log_hazard
    from app.schemas.hazard_register import HazardLog

    return log_hazard(HazardLog(**payload), db, current_user)


def _submit_permit(db: Session, current_user: CurrentUser, payload: Dict[str, Any]):
    from app.controllers.permit_workflow import worker_request_permit
    from app.schemas.permit_workflow import PermitRequest

    return worker_request_permit(PermitRequest(**payload), db, current_user)


SUBMIT_HANDLERS: Dict[str, Callable] = {
    "incident": _submit_incident,
    "permit": _submit_permit,
    "near_miss": _submit_via_report_router("app.controllers.near_miss_workflow"),
    "unsafe_act": _submit_via_report_router("app.controllers.unsafe_act_workflow"),
    "risk": _submit_via_report_router("app.controllers.risk_workflow"),
    "hazard_register": _submit_hazard_register,
}

# Families that can hold a draft. Kept wider than SUBMIT_HANDLERS on purpose:
# hazard_register, permit and audit gain their submit adapters in later phases,
# and until then a draft for one of them is still a legitimate stage-01 record —
# it just cannot be submitted yet, which /submit reports plainly.
DRAFTABLE_FAMILIES = (
    "incident", "near_miss", "unsafe_act", "risk",
    "hazard_register", "permit", "audit",
)


def _employee_id(db: Session, user_id: int) -> Optional[int]:
    return db.execute(
        text("SELECT employee_id FROM users WHERE id = :uid"), {"uid": user_id}
    ).scalar()


def _own_draft(db: Session, draft_id: int, current_user: CurrentUser) -> EventDraft:
    """A draft, and only if it belongs to the caller.

    Stricter than org scoping deliberately: an unfinished report is the author's
    until they submit it, and one worker must not be able to read or edit
    another's half-written account of an event.
    """
    row = (
        db.query(EventDraft)
        .filter(EventDraft.id == draft_id)
        .filter(EventDraft.organisation_id == current_user.org_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Draft not found")

    emp_id = _employee_id(db, current_user.user_id)
    if row.created_by is not None and row.created_by != emp_id:
        raise HTTPException(status_code=403, detail="Not your draft")
    return row


def _respond(row: EventDraft) -> dict:
    # A draft is always stage 01 by definition, so the stage block is built from
    # the literal status rather than looked up — there is no other state it
    # could be in.
    return {
        "id": row.id,
        "family": row.family,
        "payload": row.payload or {},
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "stage": workflow_stages.describe(row.family, "draft"),
    }


# ══════════════════════════════════════════════════════════════════════════════

@router.get("", response_model=List[EventDraftResponse])
@router.get("/", response_model=List[EventDraftResponse])
def list_my_drafts(
    family: Optional[str] = Query(None, description="Limit to one event family"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Everything this user has captured but not yet submitted."""
    emp_id = _employee_id(db, current_user.user_id)
    q = (
        db.query(EventDraft)
        .filter(EventDraft.organisation_id == current_user.org_id)
        .filter(EventDraft.created_by == emp_id)
    )
    if family:
        q = q.filter(EventDraft.family == family.strip().lower())
    return [_respond(r) for r in q.order_by(EventDraft.id.desc()).limit(100).all()]


@router.post("", response_model=EventDraftResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=EventDraftResponse, status_code=status.HTTP_201_CREATED)
def create_draft(
    body: EventDraftCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    family = body.family.strip().lower()
    if family not in DRAFTABLE_FAMILIES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown event family '{body.family}'. Expected one of: {', '.join(DRAFTABLE_FAMILIES)}",
        )

    row = EventDraft(
        organisation_id=current_user.org_id,
        family=family,
        created_by=_employee_id(db, current_user.user_id),
        payload=body.payload or {},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _respond(row)


@router.patch("/{draft_id}", response_model=EventDraftResponse)
def update_draft(
    draft_id: int,
    body: EventDraftUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Replace the captured payload. A draft is finished in several sittings."""
    row = _own_draft(db, draft_id, current_user)
    row.payload = body.payload or {}
    db.commit()
    db.refresh(row)
    return _respond(row)


@router.delete("/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
def discard_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    row = _own_draft(db, draft_id, current_user)
    db.delete(row)
    db.commit()


@router.post("/{draft_id}/submit")
def submit_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Stage 01 -> 02. Creates the real record, then discards the draft."""
    row = _own_draft(db, draft_id, current_user)

    handler = SUBMIT_HANDLERS.get(row.family)
    if handler is None:
        raise HTTPException(
            status_code=400,
            detail=f"Drafts for '{row.family}' cannot be submitted yet",
        )

    try:
        created = handler(db, current_user, row.payload or {})
    except HTTPException:
        # The family rejected the payload — a half-finished draft is the normal
        # case here, so the draft is kept and its own error surfaces unchanged.
        raise
    except Exception as exc:  # noqa: BLE001 — surfaced to the caller below
        raise HTTPException(status_code=400, detail=f"Draft could not be submitted: {exc}")

    # Only once the real record exists. Deleting first would lose the capture if
    # creation then failed, which is the one outcome a worker cannot recover from.
    db.delete(row)
    db.commit()

    def _attr(obj, name):
        return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)

    created_id = _attr(created, "id")
    # Read the status off whatever was created rather than assuming "reported":
    # the hazard register lands on `open`, and a future family may land somewhere
    # else again. Hardcoding it would report the wrong stage for anything that
    # does not use the report vocabulary.
    created_status = _attr(created, "workflow_status") or _attr(created, "register_status")

    return {
        "submitted": True,
        "family": row.family,
        "id": created_id,
        "stage": workflow_stages.describe(row.family, created_status),
    }
