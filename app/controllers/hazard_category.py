from typing import List, Dict
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.services.hazard_category import HazardCategoryService
from app.schemas.hazard_category import HazardCategoryCreate, HazardCategoryUpdate, HazardCategoryResponse

router = APIRouter(prefix="/hazard-categorys", tags=["Hazard Categorys"])


def _svc(db: Session = Depends(get_db)) -> HazardCategoryService:
    return HazardCategoryService(db)


@router.get("/", response_model=List[HazardCategoryResponse])
def list_hazard_categorys(skip: int = 0, limit: int = Query(100, le=1000), svc: HazardCategoryService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.list(skip=skip, limit=limit, org_id=current_user.org_id)


@router.get("/{id}", response_model=HazardCategoryResponse)
def get_hazard_category(id: int, svc: HazardCategoryService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.get(id, org_id=current_user.org_id)


@router.post("/", response_model=HazardCategoryResponse, status_code=status.HTTP_201_CREATED)
def create_hazard_category(payload: HazardCategoryCreate, svc: HazardCategoryService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.create(payload, org_id=current_user.org_id)


@router.put("/{id}", response_model=HazardCategoryResponse)
def update_hazard_category(id: int, payload: HazardCategoryUpdate, svc: HazardCategoryService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.update(id, payload, org_id=current_user.org_id)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_hazard_category(id: int, svc: HazardCategoryService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    svc.delete(id, org_id=current_user.org_id)
