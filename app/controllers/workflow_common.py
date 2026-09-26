"""Role checks and lookups shared by the permit and hazard-register workflows.

The report-workflow factory keeps its own private copies of these; this module exists
so the newer permit/hazard controllers do not have to reach into another controller's
internals. Kept intentionally tiny.
"""
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

# ── Role constants (same sets the report workflows use, plus Auditor) ─────────
WORKER_ROLES = {"Worker", "Employee", "Operator", "Technician"}
SUPERVISOR_ROLES = {"Supervisor", "Site Inspector", "Safety Manager", "Safety_Manager", "Site Engineer"}
MANAGER_ROLES = {"Manager", "HSE Manager", "Admin", "Superadmin", "Safety Manager", "Safety_Manager", "Director"}
AUDITOR_ROLES = {"Auditor"}

# Roles that may ACT on a record — acknowledge, investigate, escalate, close.
#
# Auditors are deliberately excluded. The interaction matrix in
# HSE_Web_Mobile_DataFlow gives the Auditor READ on incidents, near misses and
# unsafe acts, and the workflow chain makes step 4 "Auditor verifies
# independently". An auditor who could investigate a record would later be
# verifying their own work, which defeats the independent assurance the step
# exists to provide.
ALL_ELEVATED_ROLES = SUPERVISOR_ROLES | MANAGER_ROLES

# Anyone who may READ a workflow record, including the auditor.
ALL_READ_ROLES = SUPERVISOR_ROLES | MANAGER_ROLES | AUDITOR_ROLES


def role_matches(user_role: str, allowed: set) -> bool:
    """Case-insensitive role check — DB stores 'operator', constants say 'Operator'."""
    return (user_role or "").strip().lower() in {r.lower() for r in allowed}


def require_role(user_role: str, allowed: set, action: str) -> None:
    if not role_matches(user_role, allowed):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user_role}' is not authorized to {action}",
        )


def mobile_role_bucket(role: str) -> Optional[str]:
    """Map a raw org role name to the mobile app's 4-role vocabulary.

    Checked manager-first: "Safety Manager" sits in both SUPERVISOR_ROLES and
    MANAGER_ROLES, and mobile's normalizeRole() (mobile/src/utils/roles.ts)
    resolves it to 'manager' — this must agree or a manager's own uploads
    would silently vanish from their own training feed.
    """
    if role_matches(role, MANAGER_ROLES):
        return "manager"
    if role_matches(role, SUPERVISOR_ROLES):
        return "supervisor"
    if role_matches(role, WORKER_ROLES):
        return "worker"
    if role_matches(role, AUDITOR_ROLES):
        return "auditor"
    return None


def employee_id_for(db: Session, user_id: int) -> Optional[int]:
    row = db.execute(
        text("SELECT employee_id FROM users WHERE id = :uid"), {"uid": user_id}
    ).mappings().first()
    return row["employee_id"] if row else None


def station_id_for(db: Session, name: Optional[str], org_id: Optional[int]) -> Optional[int]:
    """Workers pick a station by name in the app; map it to an id, else leave unset."""
    if not name:
        return None
    row = db.execute(
        text(
            "SELECT id FROM working_stations "
            "WHERE station_name = :name AND organisation_id = :org_id"
        ),
        {"name": name, "org_id": org_id},
    ).mappings().first()
    return row["id"] if row else None
