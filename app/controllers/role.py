from typing import List, Dict
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.services.role import RoleService
from app.schemas.role import RoleCreate, RoleUpdate, RoleResponse

router = APIRouter(prefix="/roles", tags=["Roles"])


def _svc(db: Session = Depends(get_db)) -> RoleService:
    return RoleService(db)


@router.get("/", response_model=List[RoleResponse])
def list_roles(skip: int = 0, limit: int = Query(100, le=1000), svc: RoleService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.list(skip=skip, limit=limit, org_id=current_user.org_id)


@router.get("/{id}", response_model=RoleResponse)
def get_role(id: int, svc: RoleService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.get(id, org_id=current_user.org_id)


@router.post("/", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
def create_role(payload: RoleCreate, svc: RoleService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.create(payload, org_id=current_user.org_id)


@router.put("/{id}", response_model=RoleResponse)
def update_role(id: int, payload: RoleUpdate, svc: RoleService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.update(id, payload, org_id=current_user.org_id)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(id: int, svc: RoleService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    svc.delete(id, org_id=current_user.org_id)
