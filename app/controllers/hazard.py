from typing import List, Dict
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.services.hazard import HazardService
from app.schemas.hazard import HazardCreate, HazardUpdate, HazardResponse

router = APIRouter(prefix="/hazards", tags=["Hazards"])


def _svc(db: Session = Depends(get_db)) -> HazardService:
    return HazardService(db)


@router.get("/", response_model=List[HazardResponse])
def list_hazards(skip: int = 0, limit: int = Query(100, le=1000), svc: HazardService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.list(skip=skip, limit=limit, org_id=current_user.org_id)


@router.get("/{id}", response_model=HazardResponse)
def get_hazard(id: int, svc: HazardService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.get(id, org_id=current_user.org_id)


@router.post("/", response_model=HazardResponse, status_code=status.HTTP_201_CREATED)
def create_hazard(payload: HazardCreate, svc: HazardService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.create(payload, org_id=current_user.org_id)


@router.put("/{id}", response_model=HazardResponse)
def update_hazard(id: int, payload: HazardUpdate, svc: HazardService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.update(id, payload, org_id=current_user.org_id)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_hazard(id: int, svc: HazardService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    svc.delete(id, org_id=current_user.org_id)
