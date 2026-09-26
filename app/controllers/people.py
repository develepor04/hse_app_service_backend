from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.utils.tenant import org_scoped_join
from app.models.capa_action import CapaAction
from app.models.department import Department
from app.models.employee import Employee
from app.models.incident import Incident
from app.models.near_miss import NearMiss
from app.models.role import Role
from app.models.safety_walk import SafetyWalk
from app.models.shift_schedule import ShiftSchedule
from app.models.site import Site
from app.models.sps import SupervisorInteraction
from app.models.training_program import TrainingProgram
from app.models.competence import TrainingRecord
from app.services.rating_labels import get_rating_labels, label_and_tone

router = APIRouter(prefix="/people", tags=["People"])

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def _fmt_due(due_date) -> str:
    return due_date.strftime("%b %d, %Y") if due_date else "No Date"


def _add_months_preserve_day(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = d.day
    while True:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1


def _of(query, model, org_id):
    if org_id is not None:
        return query.filter(model.organisation_id == org_id)
    return query


@router.get("/overview")
def get_people_overview(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    today = date.today()
    org_id = current_user.org_id
    rating_labels = get_rating_labels(db, org_id)

    total_employees = _of(db.query(Employee), Employee, org_id).count() or 0

    training_incident_rows = (
        _of(
            db.query(Incident.reported_by, Incident.incident_date_time)
            .filter(
                Incident.reported_by.isnot(None),
                or_(
                    func.lower(Incident.root_cause).like("%train%"),
                    func.lower(Incident.root_cause_category).like("%train%"),
                ),
            ),
            Incident, org_id,
        ).all()
    )
    training_capa_employee_ids = {
        row[0]
        for row in _of(
            db.query(CapaAction.responsible_person_id)
            .filter(
                CapaAction.responsible_person_id.isnot(None),
                func.lower(CapaAction.root_cause_addressed).like("%train%"),
            ),
            CapaAction, org_id,
        ).all()
    }
    training_incident_employee_ids = {r[0] for r in training_incident_rows}
    flagged_now = training_capa_employee_ids | training_incident_employee_ids
    competency_pct = round((total_employees - len(flagged_now)) / total_employees * 100) if total_employees else 0

    sparkline = []
    window_start = _add_months(today, -9)
    for i in range(10):
        checkpoint = _add_months(window_start, i + 1)
        flagged_by_then = set(training_capa_employee_ids)
        for emp_id, dt in training_incident_rows:
            if dt and dt.date() < checkpoint:
                flagged_by_then.add(emp_id)
        pct = round((total_employees - len(flagged_by_then)) / total_employees * 100) if total_employees else 0
        sparkline.append(pct)

    competency_subtitle, competency_tone = label_and_tone(competency_pct, rating_labels, "workforce_competency")

    latest_incident_date = _of(db.query(func.max(Incident.incident_date_time)), Incident, org_id).scalar()
    latest_near_miss_date = _of(db.query(func.max(NearMiss.event_date_time)), NearMiss, org_id).scalar()
    candidates = [d for d in (latest_incident_date, latest_near_miss_date) if d]
    activity_anchor = max(candidates) if candidates else datetime.combine(today, datetime.min.time())
    cutoff_90 = activity_anchor - timedelta(days=90)
    recent_incidents = _of(
        db.query(Incident).filter(Incident.incident_date_time.isnot(None), Incident.incident_date_time >= cutoff_90),
        Incident, org_id,
    ).count()
    recent_near_misses = _of(
        db.query(NearMiss).filter(NearMiss.event_date_time.isnot(None), NearMiss.event_date_time >= cutoff_90),
        NearMiss, org_id,
    ).count()
    exposure_raw_pct = (recent_incidents + recent_near_misses) / total_employees * 100 if total_employees else 0.0
    exposure_index = round(min(100, exposure_raw_pct))
    exposure_subtitle, exposure_tone = label_and_tone(exposure_index, rating_labels, "workforce_exposure_risk")
    exposure_cfg = rating_labels["workforce_exposure_risk"]

    # Join through employee's actual role to check safety_signatory directly,
    # avoiding org mismatch when employees reference roles from another org.
    def _supervisor_walks_query():
        return (
            db.query(SafetyWalk, Employee)
            .join(Employee, org_scoped_join(SafetyWalk.inspector_id == Employee.id, Employee.organisation_id, org_id))
            .join(Role, Employee.role_id == Role.id)
            .filter(
                Role.safety_signatory == "Yes",
                *([SafetyWalk.organisation_id == org_id] if org_id is not None else []),
            )
        )

    avg_supervisor_compliance = _supervisor_walks_query().with_entities(func.avg(SafetyWalk.compliance_rating)).scalar()
    supervisor_walk_count = _supervisor_walks_query().count()
    supervisor_count = _supervisor_walks_query().with_entities(SafetyWalk.inspector_id).distinct().count()
    supervisor_score = round(float(avg_supervisor_compliance) / 5 * 100) if avg_supervisor_compliance else 0
    supervisor_subtitle = "Highly Effective" if supervisor_score >= 90 else ("Effective" if supervisor_score >= 70 else "Needs Coaching")
    # Was hardcoded "blue" below regardless of which of the three subtitles
    # above was picked — a supervisor scoring "Needs Coaching" rendered with
    # the exact same tone as one scoring "Highly Effective".
    supervisor_tone = "green" if supervisor_score >= 90 else ("amber" if supervisor_score >= 70 else "red")

    # Full 52-week history — the frontend's period toggle (10W/26W/52W) slices
    # the tail of this same array client-side rather than re-querying, so
    # switching windows is instant. Each point carries both a short display
    # label and the real ISO date, so the frontend can build an exact range
    # caption for whatever slice is selected.
    FATIGUE_WEEKS = 52
    latest_shift_date = _of(db.query(func.max(ShiftSchedule.shift_date)), ShiftSchedule, org_id).scalar()
    fatigue_trend: list = []
    if latest_shift_date:
        window_end = latest_shift_date + timedelta(days=1)
        window_start = window_end - timedelta(weeks=FATIGUE_WEEKS)
        shift_rows = (
            _of(
                db.query(ShiftSchedule.shift_date, ShiftSchedule.actual_hours_worked)
                .filter(ShiftSchedule.shift_date >= window_start, ShiftSchedule.shift_date < window_end),
                ShiftSchedule, org_id,
            ).all()
        )
        weekly: dict = {}
        for shift_date, hours in shift_rows:
            if shift_date is None or hours is None:
                continue
            week_index = (shift_date - window_start).days // 7
            hours = float(hours)
            normal = min(hours, 8.0)
            overtime = max(0.0, hours - 8.0)
            bucket = weekly.setdefault(week_index, {"normal": 0.0, "overtime": 0.0})
            bucket["normal"] += normal
            bucket["overtime"] += overtime
        # Each point is labelled with the calendar date its week starts on
        # (not a bare "1".."10" index) — the client flagged that a viewer had
        # no way to tell whether "week 3" meant daily, weekly, or monthly
        # buckets, let alone which weeks were being shown.
        fatigue_trend = [
            {
                "week": (window_start + timedelta(weeks=i)).strftime("%d %b"),
                "week_start": (window_start + timedelta(weeks=i)).isoformat(),
                "normal": round(weekly.get(i, {"normal": 0.0})["normal"]),
                "overtime": round(weekly.get(i, {"overtime": 0.0})["overtime"]),
            }
            for i in range(FATIGUE_WEEKS)
        ]
    fatigue_trend_range = ""
    if fatigue_trend:
        last_week_end = date.fromisoformat(fatigue_trend[-1]["week_start"]) + timedelta(days=6)
        fatigue_trend_range = (
            f"Weekly · last {FATIGUE_WEEKS} weeks "
            f"({fatigue_trend[0]['week_start']} – {last_week_end.isoformat()})"
        )


    # Full 12-month history — same client-side-slicing approach as
    # fatigue_trend above (see comment there): the frontend's period toggle
    # (6M/12M) slices the tail of this array rather than re-querying.
    TOOLBOX_MONTHS = 12
    latest_walk_date = _of(db.query(func.max(SafetyWalk.inspection_date_time)), SafetyWalk, org_id).scalar()
    walk_anchor = (latest_walk_date.date() if latest_walk_date else today)
    months_ago = _add_months(walk_anchor, -(TOOLBOX_MONTHS - 1))
    toolbox_rows = (
        _of(
            db.query(
                func.year(SafetyWalk.inspection_date_time).label("yr"),
                func.month(SafetyWalk.inspection_date_time).label("mo"),
                func.count(SafetyWalk.id).label("cnt"),
            ).filter(
                SafetyWalk.inspection_date_time.isnot(None),
                SafetyWalk.inspection_date_time >= months_ago,
            ),
            SafetyWalk, org_id,
        )
        .group_by("yr", "mo")
        .order_by("yr", "mo")
        .all()
    )
    toolbox_counts = {(int(r.yr), int(r.mo)): r.cnt for r in toolbox_rows}
    toolbox_trend = []
    for i in range(TOOLBOX_MONTHS):
        bucket_date = _add_months(months_ago, i)
        # "'26" suffix so a window spanning a year boundary (e.g. Nov-Feb)
        # never reads as ambiguous — same client note as the fatigue chart:
        # a bare month name doesn't say which year, or how many months.
        toolbox_trend.append({
            "month": f"{MONTH_NAMES[bucket_date.month - 1]} '{bucket_date.year % 100:02d}",
            "month_start": bucket_date.isoformat(),
            "meetings": toolbox_counts.get((bucket_date.year, bucket_date.month), 0),
        })
    first_bucket = _add_months(months_ago, 0)
    last_bucket = _add_months(months_ago, TOOLBOX_MONTHS - 1)
    toolbox_trend_range = (
        f"Monthly · last {TOOLBOX_MONTHS} months ({MONTH_NAMES[first_bucket.month - 1]} {first_bucket.year} – "
        f"{MONTH_NAMES[last_bucket.month - 1]} {last_bucket.year})"
    )

    role_headcount = dict(
        db.query(Role.role_name, func.count(Employee.id))
        .join(Employee, Employee.role_id == Role.id)
        .filter(*([Employee.organisation_id == org_id] if org_id is not None else []))
        .group_by(Role.role_name)
        .all()
    )
    role_incidents = dict(
        db.query(Role.role_name, func.count(Incident.id))
        .join(Employee, Employee.role_id == Role.id)
        .outerjoin(Incident, org_scoped_join(Incident.reported_by == Employee.id, Incident.organisation_id, org_id))
        .filter(*([Employee.organisation_id == org_id] if org_id is not None else []))
        .group_by(Role.role_name)
        .all()
    )
    role_near_misses = dict(
        db.query(Role.role_name, func.count(NearMiss.id))
        .join(Employee, Employee.role_id == Role.id)
        .outerjoin(NearMiss, org_scoped_join(NearMiss.reported_by == Employee.id, NearMiss.organisation_id, org_id))
        .filter(*([Employee.organisation_id == org_id] if org_id is not None else []))
        .group_by(Role.role_name)
        .all()
    )
    HIGH_RISK_ROLE_HIGH_FLOOR = 3
    HIGH_RISK_ROLE_MEDIUM_FLOOR = 1.5
    role_rates = sorted(
        (
            (name, headcount, role_incidents.get(name, 0), role_near_misses.get(name, 0),
             (role_incidents.get(name, 0) + role_near_misses.get(name, 0)) / headcount)
            for name, headcount in role_headcount.items()
            if headcount
        ),
        key=lambda item: (-item[4], item[0]),
    )
    high_risk_roles = []
    for name, headcount, incidents, near_misses, rate in role_rates[:4]:
        if rate >= HIGH_RISK_ROLE_HIGH_FLOOR:
            status, tone = "High", "red"
        elif rate >= HIGH_RISK_ROLE_MEDIUM_FLOOR:
            status, tone = "Medium", "amber"
        else:
            status, tone = "Low", "green"
        high_risk_roles.append({
            "role": name,
            "status": status,
            "tone": tone,
            # Raw inputs behind status, for the section's Info tooltip — same
            # values already computed above, not a separate/re-derived figure.
            "detail": {
                "headcount": headcount,
                "incidents": incidents,
                "near_misses": near_misses,
                "rate": round(rate, 3),
                "high_floor": HIGH_RISK_ROLE_HIGH_FLOOR,
                "medium_floor": HIGH_RISK_ROLE_MEDIUM_FLOOR,
            },
        })

    programs = _of(db.query(TrainingProgram).filter(TrainingProgram.expiry_months > 0), TrainingProgram, org_id).all()
    employees_with_induction = _of(db.query(Employee).filter(Employee.induction_date.isnot(None)), Employee, org_id).all()

    # Real completions, most recent per employee+program, take priority over the
    # induction-date projection below — only a real expires_at can ever land in
    # the past, so this is the only path that can populate "Expired".
    latest_record_by_key = {}
    training_record_rows = (
        _of(db.query(TrainingRecord).filter(TrainingRecord.training_program_id.isnot(None)), TrainingRecord, org_id)
        .order_by(TrainingRecord.completed_at.desc())
        .all()
    )
    for rec in training_record_rows:
        key = (rec.employee_id, rec.training_program_id)
        if key not in latest_record_by_key:
            latest_record_by_key[key] = rec

    expired_count = due_30_count = due_90_count = 0
    for emp in employees_with_induction:
        for prog in programs:
            record = latest_record_by_key.get((emp.id, prog.id))
            if record and record.expires_at:
                days_until = (record.expires_at - today).days
            else:
                # No completion on file yet — project the next scheduled due
                # date from induction so it can still show as upcoming, but
                # this path can never go negative, so it never counts as expired.
                next_due = emp.induction_date
                while next_due < today:
                    next_due = _add_months_preserve_day(next_due, prog.expiry_months)
                days_until = (next_due - today).days
            if days_until < 0:
                expired_count += 1
            elif days_until < 30:
                due_30_count += 1
            elif days_until < 90:
                due_90_count += 1
    training_expiry = [
        {"label": "Expired", "value": expired_count},
        {"label": "Due <30 Days", "value": due_30_count},
        {"label": "Due <90 Days", "value": due_90_count},
    ]
    expiring_soon_count = expired_count + due_30_count

    safe_count = _of(db.query(SafetyWalk).filter(SafetyWalk.issues_found == 0), SafetyWalk, org_id).count()
    at_risk_count = _of(db.query(SafetyWalk).filter(SafetyWalk.issues_found > 0), SafetyWalk, org_id).count()
    near_miss_count = _of(db.query(NearMiss), NearMiss, org_id).count()
    behaviour_total = safe_count + at_risk_count + near_miss_count
    behaviour_breakdown = [
        {"label": "Safe", "value": round(safe_count / behaviour_total * 100) if behaviour_total else 0, "color": "#50B46A"},
        {"label": "At-Risk", "value": round(at_risk_count / behaviour_total * 100) if behaviour_total else 0, "color": "#F3B548"},
        {"label": "Near Miss", "value": round(near_miss_count / behaviour_total * 100) if behaviour_total else 0, "color": "#4D74C1"},
    ]

    # Coaching sessions supervisors log via the mobile app's toolbox/coaching
    # capture (SupervisorInteraction, interaction_type="coaching") — CapaAction
    # has no "Training" action_type in this codebase (only Corrective/Preventive
    # are ever raised), so filtering on it here always returned nothing.
    coaching_rows = (
        _of(
            db.query(SupervisorInteraction, Employee)
            .outerjoin(Employee, org_scoped_join(SupervisorInteraction.employee_id == Employee.id, Employee.organisation_id, org_id))
            .filter(SupervisorInteraction.interaction_type == "coaching"),
            SupervisorInteraction, org_id,
        )
        .order_by(SupervisorInteraction.occurred_at.desc())
        .limit(3)
        .all()
    )
    coaching_actions = []
    for interaction, emp in coaching_rows:
        if not interaction.occurred_at:
            detail = "No Date"
        else:
            days_ago = (today - interaction.occurred_at.date()).days
            if days_ago <= 0:
                detail = "Today"
            elif days_ago == 1:
                detail = "Yesterday"
            else:
                detail = f"{days_ago} days ago"
        coaching_actions.append({
            "title": f"{interaction.detail or 'Coaching Session'} - {emp.full_name if emp else 'Unassigned'}",
            "detail": detail,
            "tone": "green",
        })

    open_rows = (
        _of(
            db.query(CapaAction, Employee)
            .outerjoin(Employee, org_scoped_join(CapaAction.responsible_person_id == Employee.id, Employee.organisation_id, org_id))
            .filter(CapaAction.status != "Completed"),
            CapaAction, org_id,
        )
        .order_by(case((CapaAction.due_date.is_(None), 1), else_=0), CapaAction.due_date.asc())
        .limit(3)
        .all()
    )
    open_actions = []
    for c, emp in open_rows:
        is_overdue = bool(c.due_date and c.due_date < today)
        days_until = (c.due_date - today).days if c.due_date else None
        tone = "red" if is_overdue else ("amber" if days_until is not None and days_until <= 7 else "blue")
        open_actions.append({
            "title": c.description or c.action_type or "CAPA Action",
            "detail": f"Due {_fmt_due(c.due_date)}",
            "tone": tone,
            "priority": "High" if is_overdue else "Priority",
        })

    competency_cfg = rating_labels["workforce_competency"]
    return {
        "competency_coverage": {
            "value": competency_pct,
            "subtitle": competency_subtitle,
            "tone": competency_tone,
            "change": f"{'▲' if competency_tone != 'red' else '▼'} {competency_pct}%",
            "sparkline": sparkline,
            # Raw inputs behind competency_pct, for the KPI's Info tooltip —
            # same sets already computed above, not a separate/re-derived figure.
            "detail": {
                "total_employees": total_employees,
                "flagged_employees": len(flagged_now),
                "flagged_from_incidents": len(training_incident_employee_ids),
                "flagged_from_capa": len(training_capa_employee_ids),
                "high_floor": competency_cfg["high_floor"],
                "high_label": competency_cfg["high_label"],
                "mid_floor": competency_cfg["mid_floor"],
                "mid_label": competency_cfg["mid_label"],
                "low_label": competency_cfg["low_label"],
                "sparkline_months": 9,
            },
        },
        "worker_exposure_index": {
            "value": exposure_index,
            "subtitle": exposure_subtitle,
            "tone": exposure_tone,
            "change": f"{'▲' if exposure_tone == 'green' else '⚠'}" + (f" {exposure_index}%" if exposure_tone == "green" else ""),
            # Raw inputs behind exposure_index, for the KPI's Info tooltip —
            # same values already computed above, not a separate/re-derived figure.
            "detail": {
                "total_employees": total_employees,
                "recent_incidents": recent_incidents,
                "recent_near_misses": recent_near_misses,
                "window_days": 90,
                "window_start": cutoff_90.date().isoformat(),
                "window_end": activity_anchor.date().isoformat(),
                "raw_pct": round(exposure_raw_pct, 2),
                "capped": exposure_raw_pct > 100,
                "high_floor": exposure_cfg["high_floor"],
                "high_label": exposure_cfg["high_label"],
                "mid_floor": exposure_cfg["mid_floor"],
                "mid_label": exposure_cfg["mid_label"],
                "low_label": exposure_cfg["low_label"],
            },
        },
        "supervisor_safety_score": {
            "value": supervisor_score,
            "subtitle": supervisor_subtitle,
            "tone": supervisor_tone,
            "change": f"{'▲' if supervisor_tone != 'red' else '▼'} {supervisor_score}%",
            # Raw inputs behind supervisor_score, for the KPI's Info tooltip —
            # same query already run above, not a separate/re-derived figure.
            "detail": {
                "avg_compliance_rating_1_5": round(float(avg_supervisor_compliance), 2) if avg_supervisor_compliance else None,
                "safety_walk_count": supervisor_walk_count,
                "supervisor_count": supervisor_count,
                "highly_effective_floor": 90,
                "effective_floor": 70,
            },
        },
        "fatigue_trend": fatigue_trend,
        "fatigue_trend_range": fatigue_trend_range,
        "toolbox_trend": toolbox_trend,
        "toolbox_trend_range": toolbox_trend_range,
        "high_risk_roles": high_risk_roles,
        "training_expiry": training_expiry,
        "expiring_soon_count": expiring_soon_count,
        "behaviour_breakdown": behaviour_breakdown,
        "coaching_actions": coaching_actions,
        "open_actions": open_actions,
    }


@router.get("/hierarchy")
def get_team_hierarchy(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    from app.models.user import User
    from app.models.app_role import AppRole

    org_id = current_user.org_id

    q = (
        db.query(Employee, Role, User, AppRole)
        .outerjoin(Role, Employee.role_id == Role.id)
        .outerjoin(User, User.employee_id == Employee.id)
        .outerjoin(AppRole, User.app_role_id == AppRole.id)
    )
    if org_id is not None:
        q = q.filter(Employee.organisation_id == org_id)
    rows = q.order_by(Employee.full_name.asc()).all()

    return [
        {
            "id": emp.id,
            "full_name": emp.full_name,
            "role_name": (app_role.label if app_role else None) or (role.role_name if role else None),
            "manager_id": emp.manager_id,
            "active_status": emp.active_status,
            "email": user.email if user else None,
            "has_login": user is not None,
            "is_active": bool(user.is_active) if user else None,
        }
        for emp, role, user, app_role in rows
    ]


@router.get("/directory")
def get_employee_directory(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    from app.models.user import User
    from app.models.app_role import AppRole

    org_id = current_user.org_id

    # Employees who already have a linked login (User.employee_id) are represented
    # via user_result below — exclude them here so invited users don't show twice.
    linked_employee_ids = {
        row[0] for row in db.query(User.employee_id).filter(User.employee_id.isnot(None)).all()
    }

    # Always fetch imported employees
    q = (
        db.query(Employee, Role, Department, Site)
        .outerjoin(Role, Employee.role_id == Role.id)
        .outerjoin(Department, Employee.department_id == Department.id)
        .outerjoin(Site, Department.site_id == Site.id)
    )
    if org_id is not None:
        q = q.filter(Employee.organisation_id == org_id)
    if linked_employee_ids:
        q = q.filter(Employee.id.notin_(linked_employee_ids))
    rows = q.order_by(Employee.full_name.asc()).all()

    employee_result = [
        {
            "id": emp.id,
            "full_name": emp.full_name,
            "role_name": role.role_name if role else None,
            "department_name": dept.department_name if dept else None,
            "site_name": site.site_name if site else None,
            "employment_type": emp.employment_type,
            "shift_pattern": emp.shift_pattern,
            "active_status": emp.active_status,
        }
        for emp, role, dept, site in rows
    ]

    # Always include non-admin org users (wizard step-4 / invited users)
    # Joined through to Department and Site exactly as the employee branch is.
    # These two columns used to be hardcoded None here, which meant every
    # invited user — that is, everybody the admin adds — showed a blank
    # department in the directory even though the department was saved on their
    # employee record. The site is derived (department -> site) rather than
    # stored, so it comes from the same join.
    if org_id is not None:
        uq = (
            db.query(User, AppRole, Employee, Department, Site)
            .outerjoin(AppRole, User.app_role_id == AppRole.id)
            .outerjoin(Employee, Employee.id == User.employee_id)
            .outerjoin(Department, Employee.department_id == Department.id)
            .outerjoin(Site, Department.site_id == Site.id)
            .filter(
                User.organisation_id == org_id,
                AppRole.name.notin_(["superadmin", "admin"]),
            )
        )
    else:
        uq = (
            db.query(User, AppRole, Employee, Department, Site)
            .outerjoin(AppRole, User.app_role_id == AppRole.id)
            .outerjoin(Employee, Employee.id == User.employee_id)
            .outerjoin(Department, Employee.department_id == Department.id)
            .outerjoin(Site, Department.site_id == Site.id)
            .filter(AppRole.name.notin_(["superadmin", "admin"]))
        )
    user_rows = uq.order_by(User.full_name.asc()).all()
    user_result = [
        {
            "id": -(u.id),
            "full_name": u.full_name or u.username,
            "role_name": ar.label if ar else None,
            "department_name": dept.department_name if dept else None,
            "site_name": site.site_name if site else None,
            # The employee record carries the real employment type once it is
            # set; "System User" is only the fallback for a login with no
            # employee behind it.
            "employment_type": (emp.employment_type if emp and emp.employment_type else "System User"),
            "shift_pattern": emp.shift_pattern if emp else None,
            "active_status": "Active" if u.is_active else "Inactive",
        }
        for u, ar, emp, dept, site in user_rows
    ]

    # Return system users first, then imported employees — always both
    return user_result + employee_result
