from typing import List, Dict
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.services.near_miss import NearMissService
from app.schemas.near_miss import NearMissCreate, NearMissUpdate, NearMissResponse

router = APIRouter(prefix="/near-misss", tags=["Near Misss"])


def _svc(db: Session = Depends(get_db)) -> NearMissService:
    return NearMissService(db)


@router.get("/", response_model=List[NearMissResponse])
def list_near_misss(
    skip: int = 0,
    limit: int = Query(100, le=1000),
    svc: NearMissService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.list(skip=skip, limit=limit, org_id=current_user.org_id)


@router.get("/{id}", response_model=NearMissResponse)
def get_near_miss(
    id: int,
    svc: NearMissService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.get(id, org_id=current_user.org_id)


@router.post("/", response_model=NearMissResponse, status_code=status.HTTP_201_CREATED)
def create_near_miss(
    payload: NearMissCreate,
    svc: NearMissService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.create(payload, org_id=current_user.org_id)


@router.put("/{id}", response_model=NearMissResponse)
def update_near_miss(
    id: int,
    payload: NearMissUpdate,
    svc: NearMissService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.update(id, payload, org_id=current_user.org_id)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_near_miss(
    id: int,
    svc: NearMissService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    svc.delete(id, org_id=current_user.org_id)
