from typing import List, Dict
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.services.department import DepartmentService
from app.schemas.department import DepartmentCreate, DepartmentUpdate, DepartmentResponse

router = APIRouter(prefix="/departments", tags=["Departments"])


def _svc(db: Session = Depends(get_db)) -> DepartmentService:
    return DepartmentService(db)


@router.get("/", response_model=List[DepartmentResponse])
def list_departments(skip: int = 0, limit: int = Query(100, le=1000), svc: DepartmentService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.list(skip=skip, limit=limit, org_id=current_user.org_id)


@router.get("/{id}", response_model=DepartmentResponse)
def get_department(id: int, svc: DepartmentService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.get(id, org_id=current_user.org_id)


@router.post("/", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED)
def create_department(payload: DepartmentCreate, svc: DepartmentService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.create(payload, org_id=current_user.org_id)


@router.put("/{id}", response_model=DepartmentResponse)
def update_department(id: int, payload: DepartmentUpdate, svc: DepartmentService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.update(id, payload, org_id=current_user.org_id)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_department(id: int, svc: DepartmentService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    svc.delete(id, org_id=current_user.org_id)
