"""Which supervisor a new report should land on.

Shared because there are two ways an incident gets created and they must agree:

    POST /incident-workflow/report   the workflow API
    POST /worker/incidents           what the mobile app and the web register
                                     page actually call

The second one never assigned a supervisor at all, so an incident reported from
the phone arrived with assigned_supervisor_id = NULL while one created through
the workflow API was assigned. Same event, two different outcomes, depending
only on which door it came through.
"""
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentUser
from app.models.employee import Employee

# Matched with LIKE, not equality. Organisations title the job differently --
# real data here has "Department Supervisor", "Production Supervisor", "Shift
# Supervisor" and "Shift Leader", none of which equal "Supervisor". An exact
# IN (...) list matched only "Safety Manager", which is why routing used to
# fall through to a whole-organisation fallback.
#
# Ordered by how close the title is to the job: a supervisor of the department
# beats a shift leader, and both beat a safety role, which is a level up and
# should not be the default owner of a routine report.
SUPERVISOR_ROLE_PATTERNS = [
    "%supervisor%",
    "%shift leader%",
    "%site inspector%",
    "%health & safety officer%",
    "%safety manager%",
]


def acting_employee_id(db: Session, current_user: CurrentUser) -> Optional[int]:
    """The employees.id behind the logged-in user, via users.employee_id.

    Deliberately not a name match. `full_name ILIKE %username%` only lands when
    the username happens to appear inside the person's name, so for logins like
    worker01 it matched nothing -- and every incident it touched was written
    with no reporter at all.
    """
    row = db.execute(
        text("SELECT employee_id FROM users WHERE id = :uid"),
        {"uid": current_user.user_id},
    ).mappings().first()
    return row["employee_id"] if row and row["employee_id"] else None


def find_supervisor_for(db: Session, current_user: CurrentUser) -> Optional[int]:
    """The supervisor a report from this person should land on.

    Three tiers, most specific first:

      1. the reporter's own manager, when one is recorded
      2. an active supervisor in the reporter's OWN DEPARTMENT
      3. nobody -- the report stays unassigned in the shared queue

    Tier 3 used to be "any active supervisor in the organisation", chosen by
    .first() with no ORDER BY. That is worse than leaving it blank: every
    report landed on whichever row the database happened to return first,
    producing a named owner with no connection to the reporter or the work.
    The department-scoped queue still shows unassigned reports to the right
    people, so nothing is lost by declining to guess.
    """
    from app.models.role import Role

    reporter_id = acting_employee_id(db, current_user)
    reporter = (
        db.query(Employee).filter(Employee.id == reporter_id).first()
        if reporter_id else None
    )

    if reporter and reporter.manager_id:
        return reporter.manager_id

    if reporter and reporter.department_id:
        for pattern in SUPERVISOR_ROLE_PATTERNS:
            match = (
                db.query(Employee)
                .join(Role, Employee.role_id == Role.id)
                .filter(Employee.organisation_id == current_user.org_id)
                .filter(Employee.department_id == reporter.department_id)
                .filter(Employee.id != reporter.id)   # nobody supervises themselves
                .filter(Role.role_name.ilike(pattern))
                .filter(Employee.active_status == "Active")
                .order_by(Employee.id)
                .first()
            )
            if match:
                return match.id

    return None
