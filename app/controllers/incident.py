import math
from typing import List, Dict, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.services.incident import IncidentService
from app.schemas.incident import IncidentCreate, IncidentUpdate, IncidentResponse, IncidentPage
from app.models.incident import Incident

router = APIRouter(prefix="/incidents", tags=["Incidents"])


def _svc(db: Session = Depends(get_db)) -> IncidentService:
    return IncidentService(db)


@router.get("/", response_model=List[IncidentResponse])
def list_incidents(
    skip: int = 0,
    limit: int = Query(100, le=1000),
    svc: IncidentService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.list(skip=skip, limit=limit, org_id=current_user.org_id)


@router.get("/all", response_model=IncidentPage)
def list_incidents_paginated(
    page: int = 1,
    pageSize: int = 25,
    status: Optional[str] = Query(None),
    incident_type: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Matches incident description"),
    svc: IncidentService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    page = max(page, 1)
    pageSize = max(pageSize, 1)
    skip = (page - 1) * pageSize
    org_id = current_user.org_id
    if any([status, incident_type, severity, source, q]):
        total = svc.count_filtered(org_id, status, incident_type, severity, source, q)
        data = svc.list_filtered(org_id, skip=skip, limit=pageSize, status=status,
                                  incident_type=incident_type, severity=severity, source=source, q=q)
    else:
        total = svc.count(org_id=org_id)
        data = svc.list(skip=skip, limit=pageSize, org_id=org_id)
    return IncidentPage(
        data=data,
        total=total,
        page=page,
        pageSize=pageSize,
        totalPages=math.ceil(total / pageSize) if total else 0,
    )


@router.get("/filter-options")
def get_incident_filter_options(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Distinct incident types/severities/statuses actually on record for this
    org, so the "All Incidents" filter dropdowns only ever offer real,
    selectable values instead of a hardcoded guess."""
    org_id = current_user.org_id
    base = db.query(Incident).filter(Incident.organisation_id == org_id) if org_id is not None else db.query(Incident)

    types = [r[0] for r in base.with_entities(func.distinct(Incident.incident_type)).all() if r[0]]
    severities = [r[0] for r in base.with_entities(func.distinct(Incident.severity)).all() if r[0]]
    statuses = [r[0] for r in base.with_entities(func.distinct(Incident.investigation_status)).all() if r[0]]
    return {"types": sorted(types), "severities": sorted(severities), "statuses": sorted(statuses)}


@router.get("/{id}", response_model=IncidentResponse)
def get_incident(
    id: int,
    svc: IncidentService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.get(id, org_id=current_user.org_id)


@router.post("/", response_model=IncidentResponse, status_code=status.HTTP_201_CREATED)
def create_incident(
    payload: IncidentCreate,
    svc: IncidentService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.create(payload, org_id=current_user.org_id)


@router.put("/{id}", response_model=IncidentResponse)
def update_incident(
    id: int,
    payload: IncidentUpdate,
    svc: IncidentService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.update(id, payload, org_id=current_user.org_id)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_incident(
    id: int,
    svc: IncidentService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    svc.delete(id, org_id=current_user.org_id)
