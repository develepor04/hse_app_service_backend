from typing import List, Dict
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.services.permit_to_work import PermitToWorkService
from app.schemas.permit_to_work import PermitToWorkCreate, PermitToWorkUpdate, PermitToWorkResponse

router = APIRouter(prefix="/permit-to-works", tags=["Permit To Works"])


def _svc(db: Session = Depends(get_db)) -> PermitToWorkService:
    return PermitToWorkService(db)


@router.get("/", response_model=List[PermitToWorkResponse])
def list_permit_to_works(skip: int = 0, limit: int = Query(100, le=1000), svc: PermitToWorkService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.list(skip=skip, limit=limit, org_id=current_user.org_id)


@router.get("/{id}", response_model=PermitToWorkResponse)
def get_permit_to_work(id: int, svc: PermitToWorkService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.get(id, org_id=current_user.org_id)


@router.post("/", response_model=PermitToWorkResponse, status_code=status.HTTP_201_CREATED)
def create_permit_to_work(payload: PermitToWorkCreate, svc: PermitToWorkService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.create(payload, org_id=current_user.org_id)


@router.put("/{id}", response_model=PermitToWorkResponse)
def update_permit_to_work(id: int, payload: PermitToWorkUpdate, svc: PermitToWorkService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.update(id, payload, org_id=current_user.org_id)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_permit_to_work(id: int, svc: PermitToWorkService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    svc.delete(id, org_id=current_user.org_id)
