from typing import List, Dict
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.services.policy import PolicyService
from app.schemas.policy import PolicyCreate, PolicyUpdate, PolicyResponse

router = APIRouter(prefix="/policys", tags=["Policys"])


def _svc(db: Session = Depends(get_db)) -> PolicyService:
    return PolicyService(db)


@router.get("/", response_model=List[PolicyResponse])
def list_policys(skip: int = 0, limit: int = Query(100, le=1000), svc: PolicyService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.list(skip=skip, limit=limit, org_id=current_user.org_id)


@router.get("/{id}", response_model=PolicyResponse)
def get_policy(id: int, svc: PolicyService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.get(id, org_id=current_user.org_id)


@router.post("/", response_model=PolicyResponse, status_code=status.HTTP_201_CREATED)
def create_policy(payload: PolicyCreate, svc: PolicyService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.create(payload, org_id=current_user.org_id)


@router.put("/{id}", response_model=PolicyResponse)
def update_policy(id: int, payload: PolicyUpdate, svc: PolicyService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.update(id, payload, org_id=current_user.org_id)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_policy(id: int, svc: PolicyService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    svc.delete(id, org_id=current_user.org_id)
