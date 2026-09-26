from typing import List, Dict
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.services.capa_action import CapaActionService
from app.schemas.capa_action import CapaActionCreate, CapaActionUpdate, CapaActionResponse

router = APIRouter(prefix="/capa-actions", tags=["Capa Actions"])


def _svc(db: Session = Depends(get_db)) -> CapaActionService:
    return CapaActionService(db)


@router.get("/", response_model=List[CapaActionResponse])
def list_capa_actions(
    skip: int = 0,
    limit: int = Query(100, le=1000),
    svc: CapaActionService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.list(skip=skip, limit=limit, org_id=current_user.org_id)


@router.get("/{id}", response_model=CapaActionResponse)
def get_capa_action(
    id: int,
    svc: CapaActionService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.get(id, org_id=current_user.org_id)


@router.post("/", response_model=CapaActionResponse, status_code=status.HTTP_201_CREATED)
def create_capa_action(
    payload: CapaActionCreate,
    svc: CapaActionService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.create(payload, org_id=current_user.org_id)


@router.put("/{id}", response_model=CapaActionResponse)
def update_capa_action(
    id: int,
    payload: CapaActionUpdate,
    svc: CapaActionService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.update(id, payload, org_id=current_user.org_id)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_capa_action(
    id: int,
    svc: CapaActionService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    svc.delete(id, org_id=current_user.org_id)
