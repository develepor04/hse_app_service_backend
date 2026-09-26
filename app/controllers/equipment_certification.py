from datetime import date, timedelta
from typing import Optional, List, Dict

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.models.equipment_certification import EquipmentCertification
from app.models.site import Site

router = APIRouter(prefix="/equipment-certifications", tags=["Equipment Certifications"])

EXPIRING_SOON_DAYS = 30


def _cert_status(expiry_date: Optional[date]) -> str:
    if not expiry_date:
        return "Valid"
    today = date.today()
    if expiry_date < today:
        return "Expired"
    if expiry_date <= today + timedelta(days=EXPIRING_SOON_DAYS):
        return "Expiring Soon"
    return "Valid"


def _fmt_date(d: Optional[date]) -> str:
    return d.strftime("%Y-%m-%d") if d else ""


def _to_response(cert: EquipmentCertification, site_name: Optional[str]) -> dict:
    return {
        "Cert_ID": f"CERT-{cert.id:04d}",
        "Equipment_Name": cert.equipment_name,
        "Equipment_Type": cert.equipment_type or "",
        "Site_ID": site_name or "—",
        "Zone_ID": cert.zone or "—",
        "Serial_Number": cert.serial_number or "",
        "Manufacturer": cert.manufacturer or "",
        "Model": cert.model or "",
        "Certification_Type": cert.certification_type or "",
        "Certified_By": cert.certified_by or "",
        "Issue_Date": _fmt_date(cert.issue_date),
        "Expiry_Date": _fmt_date(cert.expiry_date),
        "Next_Inspection": _fmt_date(cert.next_inspection_date),
        "Status": _cert_status(cert.expiry_date),
        "Compliance_Standard": cert.compliance_standard or "",
    }


@router.get("/")
def list_certifications(
    status: Optional[str] = None,
    equipment_type: Optional[str] = None,
    site_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    org_id = current_user.org_id
    q = db.query(EquipmentCertification)
    if org_id is not None:
        q = q.filter(EquipmentCertification.organisation_id == org_id)
    if equipment_type:
        q = q.filter(EquipmentCertification.equipment_type == equipment_type)
    if site_id:
        q = q.filter(EquipmentCertification.site_id == site_id)

    rows = q.order_by(EquipmentCertification.expiry_date.asc()).all()

    site_ids = {r.site_id for r in rows if r.site_id}
    site_map: Dict[int, str] = {}
    if site_ids:
        for s in db.query(Site).filter(Site.id.in_(site_ids)).all():
            site_map[s.id] = s.site_name

    results = [_to_response(r, site_map.get(r.site_id)) for r in rows]

    # Apply status filter after computing derived status
    if status:
        results = [r for r in results if r["Status"] == status]

    return results


class CertCreate(BaseModel):
    equipment_name: str
    equipment_type: Optional[str] = None
    site_id: Optional[int] = None
    zone: Optional[str] = None
    serial_number: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    certification_type: Optional[str] = None
    certified_by: Optional[str] = None
    issue_date: Optional[date] = None
    expiry_date: Optional[date] = None
    next_inspection_date: Optional[date] = None
    compliance_standard: Optional[str] = None


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_certification(
    payload: CertCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    org_id = current_user.org_id
    cert = EquipmentCertification(organisation_id=org_id, **payload.model_dump())
    db.add(cert)
    db.commit()
    db.refresh(cert)

    site_name = None
    if cert.site_id:
        s = db.query(Site).filter(Site.id == cert.site_id).first()
        site_name = s.site_name if s else None

    return _to_response(cert, site_name)


@router.delete("/{cert_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_certification(
    cert_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    org_id = current_user.org_id
    q = db.query(EquipmentCertification).filter(EquipmentCertification.id == cert_id)
    if org_id is not None:
        q = q.filter(EquipmentCertification.organisation_id == org_id)
    cert = q.first()
    if cert:
        db.delete(cert)
        db.commit()
