from typing import List, Dict
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.services.site import SiteService
from app.schemas.site import SiteCreate, SiteUpdate, SiteResponse

router = APIRouter(prefix="/sites", tags=["Sites"])


def _svc(db: Session = Depends(get_db)) -> SiteService:
    return SiteService(db)


@router.get("/", response_model=List[SiteResponse])
def list_sites(skip: int = 0, limit: int = Query(100, le=1000), svc: SiteService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.list(skip=skip, limit=limit, org_id=current_user.org_id)


@router.get("/{id}", response_model=SiteResponse)
def get_site(id: int, svc: SiteService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.get(id, org_id=current_user.org_id)


@router.post("/", response_model=SiteResponse, status_code=status.HTTP_201_CREATED)
def create_site(payload: SiteCreate, svc: SiteService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.create(payload, org_id=current_user.org_id)


@router.put("/{id}", response_model=SiteResponse)
def update_site(id: int, payload: SiteUpdate, svc: SiteService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    return svc.update(id, payload, org_id=current_user.org_id)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_site(id: int, svc: SiteService = Depends(_svc), current_user: CurrentUser = Depends(get_current_user)):
    svc.delete(id, org_id=current_user.org_id)
