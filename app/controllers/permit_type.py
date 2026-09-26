from typing import List, Dict
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.services.permit_type import PermitTypeService
from app.schemas.permit_type import PermitTypeCreate, PermitTypeUpdate, PermitTypeResponse

router = APIRouter(prefix="/permit-types", tags=["Permit Types"])


def _svc(db: Session = Depends(get_db)) -> PermitTypeService:
    return PermitTypeService(db)


@router.get("/", response_model=List[PermitTypeResponse])
def list_permit_types(skip: int = 0, limit: int = Query(100, le=1000), svc: PermitTypeService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.list(skip=skip, limit=limit, org_id=current_user.org_id)


@router.get("/{id}", response_model=PermitTypeResponse)
def get_permit_type(id: int, svc: PermitTypeService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.get(id, org_id=current_user.org_id)


@router.post("/", response_model=PermitTypeResponse, status_code=status.HTTP_201_CREATED)
def create_permit_type(payload: PermitTypeCreate, svc: PermitTypeService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.create(payload, org_id=current_user.org_id)


@router.put("/{id}", response_model=PermitTypeResponse)
def update_permit_type(id: int, payload: PermitTypeUpdate, svc: PermitTypeService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.update(id, payload, org_id=current_user.org_id)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_permit_type(id: int, svc: PermitTypeService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    svc.delete(id, org_id=current_user.org_id)
