from typing import List, Dict
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.services.working_station import WorkingStationService
from app.schemas.working_station import WorkingStationCreate, WorkingStationUpdate, WorkingStationResponse

router = APIRouter(prefix="/working-stations", tags=["Working Stations"])


def _svc(db: Session = Depends(get_db)) -> WorkingStationService:
    return WorkingStationService(db)


@router.get("/", response_model=List[WorkingStationResponse])
def list_working_stations(skip: int = 0, limit: int = Query(100, le=1000), svc: WorkingStationService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.list(skip=skip, limit=limit, org_id=current_user.org_id)


@router.get("/{id}", response_model=WorkingStationResponse)
def get_working_station(id: int, svc: WorkingStationService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.get(id, org_id=current_user.org_id)


@router.post("/", response_model=WorkingStationResponse, status_code=status.HTTP_201_CREATED)
def create_working_station(payload: WorkingStationCreate, svc: WorkingStationService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.create(payload, org_id=current_user.org_id)


@router.put("/{id}", response_model=WorkingStationResponse)
def update_working_station(id: int, payload: WorkingStationUpdate, svc: WorkingStationService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.update(id, payload, org_id=current_user.org_id)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_working_station(id: int, svc: WorkingStationService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    svc.delete(id, org_id=current_user.org_id)
