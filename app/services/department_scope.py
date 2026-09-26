"""Who sees which records, by department.

The org admin fixes a department on every employee at the point they are added.
From then on a report belongs to the reporter's department, and only that
department's supervisor and manager should be working it — a supervisor in
Finishing has no business acknowledging a Maintenance near miss.

Records carry no department of their own. The department is the *reporter's*,
resolved through the reporter column each family happens to use:

    incidents / near_misses / unsafe_acts / risk_reports   reported_by
    hazards                                                logged_by
    permits_to_work                                        requested_by

so the scope is applied as a subquery on that column rather than a plain
WHERE, which keeps it usable on every family without adding a column to six
tables.

Two deliberate exemptions, both to stop records becoming invisible:

  · ORG_WIDE_ROLES see everything in their organisation. An Admin who could
    only see their own department could not administer the org, and an Auditor
    exists precisely to look across departments.

  · A record whose reporter has no department is shown to everyone in the org.
    Filtering it out would leave it in nobody's queue, which is how a report
    goes unactioned forever. The same applies to a viewer who has no department
    themselves — they fall back to org-wide rather than seeing an empty screen
    and assuming there is no work.
"""
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentUser

# Roles that legitimately look across every department.
ORG_WIDE_ROLES = {"admin", "superadmin", "auditor"}


def sees_whole_org(role: Optional[str]) -> bool:
    return (role or "").strip().lower().replace(" ", "_") in ORG_WIDE_ROLES


def viewer_department_id(db: Session, current_user: CurrentUser) -> Optional[int]:
    """The department of the logged-in person, or None if they have no employee
    record or no department on it.

    Resolved through users.employee_id -> employees.department_id. Deliberately
    not through a name match: `full_name ILIKE %username%` is what made
    supervisor routing silently never resolve for logins like worker01.
    """
    row = db.execute(
        text(
            "SELECT e.department_id "
            "  FROM users u "
            "  JOIN employees e ON e.id = u.employee_id "
            " WHERE u.id = :uid"
        ),
        {"uid": current_user.user_id},
    ).mappings().first()
    return row["department_id"] if row and row["department_id"] else None


def scope_sql(reporter_column: str) -> str:
    """A SQL fragment restricting rows to the viewer's department.

    Takes the reporter column because each family names it differently. Binds
    one parameter, :viewer_dept, which callers supply from
    `viewer_department_id`. Returns an always-true fragment when the caller
    decides no scoping applies, so call sites can concatenate unconditionally.

    The `IS NULL` arm is the safety valve: a reporter with no department is
    visible to the whole organisation rather than to nobody.
    """
    return (
        f" AND ({reporter_column} IS NULL"
        f"      OR EXISTS (SELECT 1 FROM employees de"
        f"                  WHERE de.id = {reporter_column}"
        f"                    AND (de.department_id = :viewer_dept"
        f"                         OR de.department_id IS NULL)))"
    )


def apply_scope(query, model, reporter_attr: str, db: Session, current_user: CurrentUser):
    """SQLAlchemy-query equivalent of `scope_sql`, for the ORM call sites.

    Returns the query unchanged when the viewer sees the whole organisation, or
    has no department of their own — see the module docstring for why that
    falls back to org-wide rather than to nothing.
    """
    if sees_whole_org(current_user.role):
        return query
    dept_id = viewer_department_id(db, current_user)
    if dept_id is None:
        return query

    from app.models.employee import Employee

    column = getattr(model, reporter_attr)
    same_dept = (
        db.query(Employee.id)
        .filter(Employee.department_id == dept_id)
        .subquery()
    )
    no_dept = (
        db.query(Employee.id)
        .filter(Employee.department_id.is_(None))
        .subquery()
    )
    return query.filter(
        (column.is_(None))
        | column.in_(db.query(same_dept.c.id))
        | column.in_(db.query(no_dept.c.id))
    )
