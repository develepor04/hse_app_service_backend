from typing import List, Dict
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.services.training_program import TrainingProgramService
from app.schemas.training_program import TrainingProgramCreate, TrainingProgramUpdate, TrainingProgramResponse

router = APIRouter(prefix="/training-programs", tags=["Training Programs"])


def _svc(db: Session = Depends(get_db)) -> TrainingProgramService:
    return TrainingProgramService(db)


@router.get("/", response_model=List[TrainingProgramResponse])
def list_training_programs(skip: int = 0, limit: int = Query(100, le=1000), svc: TrainingProgramService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.list(skip=skip, limit=limit, org_id=current_user.org_id)


@router.get("/{id}", response_model=TrainingProgramResponse)
def get_training_program(id: int, svc: TrainingProgramService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.get(id, org_id=current_user.org_id)


@router.post("/", response_model=TrainingProgramResponse, status_code=status.HTTP_201_CREATED)
def create_training_program(payload: TrainingProgramCreate, svc: TrainingProgramService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.create(payload, org_id=current_user.org_id)


@router.put("/{id}", response_model=TrainingProgramResponse)
def update_training_program(id: int, payload: TrainingProgramUpdate, svc: TrainingProgramService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.update(id, payload, org_id=current_user.org_id)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_training_program(id: int, svc: TrainingProgramService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    svc.delete(id, org_id=current_user.org_id)
