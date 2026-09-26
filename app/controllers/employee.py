from typing import List, Dict
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.services.employee import EmployeeService
from app.schemas.employee import (
    EmployeeCreate,
    EmployeeUpdate,
    EmployeeResponse,
    MyProfileUpdate,
    MyPhotoUpdate,
)

router = APIRouter(prefix="/employees", tags=["Employees"])


def _svc(db: Session = Depends(get_db)) -> EmployeeService:
    return EmployeeService(db)


@router.get("/", response_model=List[EmployeeResponse])
def list_employees(
    skip: int = 0,
    limit: int = Query(100, le=1000),
    svc: EmployeeService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.list(skip=skip, limit=limit, org_id=current_user.org_id)


# Declared before /{id} so the literal "me" is not parsed as an employee id.
@router.get("/me")
def get_my_profile(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Full profile for the signed-in user, with role/department/manager resolved."""
    row = db.execute(
        text("""
            SELECT e.*,
                   r.role_name        AS role_name,
                   d.department_name  AS department_name,
                   m.full_name        AS manager_name,
                   u.username         AS username,
                   u.email            AS email
            FROM users e_u
            JOIN employees e      ON e.id = e_u.employee_id
            LEFT JOIN roles r     ON r.id = e.role_id
            LEFT JOIN departments d ON d.id = e.department_id
            LEFT JOIN employees m ON m.id = e.manager_id
            JOIN users u          ON u.id = e_u.id
            WHERE e_u.id = :uid
        """),
        {"uid": current_user.user_id},
    ).mappings().first()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No employee record linked to this user",
        )

    def _d(v):
        return v.isoformat() if v is not None and hasattr(v, "isoformat") else v

    return {
        "employee_id":           row["id"],
        "full_name":             row["full_name"],
        "photo":                 row["photo_base64"],
        "username":              row["username"],
        "email":                 row["email"],
        "role_name":             row["role_name"],
        "department_name":       row["department_name"],
        "manager_name":          row["manager_name"],
        "date_of_birth":         _d(row["date_of_birth"]),
        "gender":                row["gender"],
        "employment_type":       row["employment_type"],
        "employment_start_date": _d(row["employment_start_date"]),
        "shift_pattern":         row["shift_pattern"],
        "induction_date":        _d(row["induction_date"]),
        "active_status":         row["active_status"],
    }


@router.put("/me/photo")
def set_my_photo(
    payload: MyPhotoUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Replace (or clear) the caller's own profile photo.

    Target row comes from the JWT, so a caller cannot overwrite someone else's
    photo. Pass photo=null to remove.
    """
    emp_id = db.execute(
        text("SELECT employee_id FROM users WHERE id = :uid"),
        {"uid": current_user.user_id},
    ).scalar()

    if not emp_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No employee record linked to this user",
        )

    db.execute(
        text("UPDATE employees SET photo_base64 = :p WHERE id = :emp_id"),
        {"p": payload.photo, "emp_id": emp_id},
    )
    db.commit()
    return {"employee_id": emp_id, "has_photo": payload.photo is not None}


@router.patch("/me")
def update_my_profile(
    payload: MyProfileUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Update the self-editable fields on the caller's OWN employee record.

    The target row is resolved from the JWT, never from client input, so a caller
    cannot address another employee. See MyProfileUpdate for the allowed fields.
    """
    emp_id = db.execute(
        text("SELECT employee_id FROM users WHERE id = :uid"),
        {"uid": current_user.user_id},
    ).scalar()

    if not emp_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No employee record linked to this user",
        )

    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No editable fields supplied",
        )

    assignments = ", ".join(f"{col} = :{col}" for col in changes)
    db.execute(
        text(f"UPDATE employees SET {assignments} WHERE id = :emp_id"),
        {**changes, "emp_id": emp_id},
    )
    db.commit()

    return get_my_profile(db=db, current_user=current_user)


@router.get("/{id}", response_model=EmployeeResponse)
def get_employee(
    id: int,
    svc: EmployeeService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.get(id, org_id=current_user.org_id)


@router.post("/", response_model=EmployeeResponse, status_code=status.HTTP_201_CREATED)
def create_employee(
    payload: EmployeeCreate,
    svc: EmployeeService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.create(payload, org_id=current_user.org_id)


@router.put("/{id}", response_model=EmployeeResponse)
def update_employee(
    id: int,
    payload: EmployeeUpdate,
    svc: EmployeeService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.update(id, payload, org_id=current_user.org_id)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_employee(
    id: int,
    svc: EmployeeService = Depends(_svc),
    current_user: CurrentUser = Depends(get_current_user),
):
    svc.delete(id, org_id=current_user.org_id)
