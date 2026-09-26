"""One-off data repair: put the demo employee rows in the org their logins work in.

`worker01` and `supervisor01` sign in as organisation 4 (WindTech, the org that
holds the demo data) while their *employee* rows sat in organisation 1. Every
tenant-scoped read joins on both, so the two disagreeing is not cosmetic:

  · `capa_owners.assignable_owners` requires `users.organisation_id` AND
    `employees.organisation_id` to match — deliberately, because that is exactly
    the set the assign write will accept. With the rows in org 1, neither of
    them could be offered as a CAPA owner or assigned one, and the picker showed
    a two-person organisation.
  · the same pair is why `repair_employee_ref_org_mismatch.py` exists at all.
    That script clears the *references*; this one fixes the *rows*, which is the
    right direction when the employee genuinely works in the other org.

And they do: nearly all of their activity is already org 4 — 21 incidents, 32
near misses, 157 permits and 8 hazards for employee 21 alone. The org-1 row was
the outlier, not the work.

Three columns move together, because an employee in org 4 pointing at an org-1
department or line manager is the same defect one level down:

    organisation_id  1 -> 4
    department_id    to the org-4 department of the same name
    manager_id       to the reporting line the demo actually uses —
                     worker01 -> supervisor01 -> Manager One

That last one is not tidiness. `capa_notify.supervisor_of` reads
`employees.manager_id` to find who to escalate a corrective action to at 90% of
its deadline; with it pointing at an org-1 employee the chain fell through to
the safety-manager fallback every time.

Non-destructive: the previous values are copied into `_employee_org_move_backup`
first, so the move can be undone.

Usage:
    python scripts/move_demo_logins_to_org4.py            # dry run
    python scripts/move_demo_logins_to_org4.py --apply    # apply
"""
import argparse
import os

import pymysql
from dotenv import load_dotenv

load_dotenv()

TARGET_ORG = 4

# username -> the department name to match in the target org. Matched by name
# rather than by a hardcoded id: org 4 carries departments of the same names,
# and a name survives a reseed where an id does not.
MOVES = {
    "worker01": "Finishing",
    "supervisor01": "Planning & Scheduling",
}

# The reporting line the demo is meant to show. Resolved by username so the
# script does not carry employee ids that a reseed would invalidate.
REPORTS_TO = {
    "worker01": "supervisor01",
    "supervisor01": "manager01",
}


def get_connection():
    return pymysql.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "hse_db"),
    )


def employee_of(cur, username):
    cur.execute(
        """
        SELECT e.id, e.full_name, e.organisation_id, e.department_id, e.manager_id,
               u.organisation_id
        FROM users u JOIN employees e ON e.id = u.employee_id
        WHERE u.username = %s
        """,
        (username,),
    )
    return cur.fetchone()


def department_in_org(cur, name, org_id):
    cur.execute(
        "SELECT id FROM departments WHERE department_name = %s AND organisation_id = %s LIMIT 1",
        (name, org_id),
    )
    row = cur.fetchone()
    return row[0] if row else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually write changes. Without this flag, only reports what would change.",
    )
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    plan = []
    for username, dept_name in MOVES.items():
        emp = employee_of(cur, username)
        if not emp:
            print(f"{username}: no employee row linked to this login — skipped")
            continue
        emp_id, full_name, emp_org, dept_id, mgr_id, login_org = emp

        dept_target = department_in_org(cur, dept_name, TARGET_ORG)
        if dept_target is None:
            print(f"{username}: org {TARGET_ORG} has no '{dept_name}' department — "
                  f"leaving department_id as it is")

        mgr_username = REPORTS_TO.get(username)
        mgr_target = None
        if mgr_username:
            mgr = employee_of(cur, mgr_username)
            mgr_target = mgr[0] if mgr else None
            if mgr_target is None:
                print(f"{username}: no employee row for {mgr_username} — "
                      f"leaving manager_id as it is")

        print(
            f"{username} (employee {emp_id}, {full_name}): "
            f"login org {login_org}, employee org {emp_org}\n"
            f"    organisation_id  {emp_org} -> {TARGET_ORG}\n"
            f"    department_id    {dept_id} -> {dept_target if dept_target else dept_id}\n"
            f"    manager_id       {mgr_id} -> {mgr_target if mgr_target else mgr_id}"
        )
        if emp_org != TARGET_ORG or dept_target or mgr_target:
            plan.append((emp_id, emp_org, dept_id, mgr_id, dept_target, mgr_target))

    if not plan:
        print("\nNothing to move — the employee rows already sit in the target org.")
        return

    if not args.apply:
        print(f"\nDry run only — {len(plan)} employee row(s) would move. "
              f"Re-run with --apply to back up and write them.")
        return

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS _employee_org_move_backup (
            employee_id INT NOT NULL PRIMARY KEY,
            old_organisation_id INT,
            old_department_id INT,
            old_manager_id INT,
            moved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    for emp_id, old_org, old_dept, old_mgr, dept_target, mgr_target in plan:
        cur.execute(
            """
            INSERT INTO _employee_org_move_backup
                (employee_id, old_organisation_id, old_department_id, old_manager_id)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE employee_id = employee_id
            """,
            (emp_id, old_org, old_dept, old_mgr),
        )
        cur.execute(
            """
            UPDATE employees
               SET organisation_id = %s,
                   department_id  = COALESCE(%s, department_id),
                   manager_id     = COALESCE(%s, manager_id)
             WHERE id = %s
            """,
            (TARGET_ORG, dept_target, mgr_target, emp_id),
        )

    conn.commit()
    print(f"\nMoved {len(plan)} employee row(s) to organisation {TARGET_ORG}. "
          f"Previous values are in _employee_org_move_backup.")


if __name__ == "__main__":
    main()
