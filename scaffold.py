"""
Scaffolds the full MVC / three-tier architecture for the HSE FastAPI project.
Run once from the backend/ directory:  python scaffold.py
"""

import os
from pathlib import Path

ROOT = Path(__file__).parent / "app"

# ---------------------------------------------------------------------------
# Entity metadata
# Each entry: (module_name, class_name, table_name, fields)
# fields: list of (col_name, sa_type_str, nullable, fk_or_None)
# ---------------------------------------------------------------------------
ENTITIES = [
    (
        "organisation", "Organisation", "organisation",
        [
            ("organisation_name", "String(255)", False, None),
            ("country",           "String(100)", True,  None),
            ("industry_sector",   "String(100)", True,  None),
            ("number_of_employees", "Integer",   True,  None),
            ("headquarters_location", "String(255)", True, None),
            ("parent_company",    "String(255)", True,  None),
            ("iso_45001_status",  "String(50)",  True,  None),
            ("regulatory_authority", "String(255)", True, None),
            ("establishment_date", "Date",        True,  None),
        ],
    ),
    (
        "hazard_category", "HazardCategory", "hazard_categories",
        [
            ("category_name", "String(100)", False, None),
            ("description",   "Text",        True,  None),
        ],
    ),
    (
        "hazard", "Hazard", "hazards",
        [
            ("category_id",  "Integer", False, "hazard_categories.id"),
            ("hazard_name",  "String(255)", False, None),
            ("severity",     "String(50)",  True,  None),
            ("probability",  "String(50)",  True,  None),
        ],
    ),
    (
        "role", "Role", "roles",
        [
            ("role_name",        "String(100)", False, None),
            ("job_category",     "String(100)", True,  None),
            ("authority_level",  "Integer",     True,  None),
            ("permit_authority", "String(10)",  True,  None),
            ("safety_signatory", "String(10)",  True,  None),
        ],
    ),
    (
        "site", "Site", "sites",
        [
            ("site_name",                   "String(255)", False, None),
            ("address",                     "String(255)", True,  None),
            ("postcode",                    "String(20)",  True,  None),
            ("city",                        "String(100)", True,  None),
            ("type",                        "String(100)", True,  None),
            ("operational_status",          "String(50)",  True,  None),
            ("number_of_working_stations",  "Integer",     True,  None),
            ("capacity",                    "Integer",     True,  None),
            ("primary_products",            "String(255)", True,  None),
            ("hazard_classification",       "String(50)",  True,  None),
        ],
    ),
    (
        "permit_type", "PermitType", "permit_types",
        [
            ("permit_type_name",      "String(255)", False, None),
            ("risk_level",            "String(50)",  True,  None),
            ("validity_period_hours", "Integer",     True,  None),
            ("concurrent_limit",      "Integer",     True,  None),
        ],
    ),
    (
        "training_program", "TrainingProgram", "training_programs",
        [
            ("training_name",  "String(255)", False, None),
            ("duration_hours", "Integer",     True,  None),
            ("frequency",      "String(50)",  True,  None),
            ("certification",  "String(10)",  True,  None),
            ("expiry_months",  "Integer",     True,  None),
        ],
    ),
    (
        "policy", "Policy", "policies",
        [
            ("policy_name", "String(255)", False, None),
            ("category",    "String(100)", True,  None),
            ("issue_date",  "Date",        True,  None),
            ("owner",       "String(100)", True,  None),
            ("status",      "String(50)",  True,  None),
        ],
    ),
    (
        "department", "Department", "departments",
        [
            ("site_id",         "Integer",     False, "sites.id"),
            ("department_name", "String(255)", False, None),
            ("manager_id",      "Integer",     True,  "employees.id"),
            ("number_of_teams", "Integer",     True,  None),
        ],
    ),
    (
        "working_station", "WorkingStation", "working_stations",
        [
            ("station_name",          "String(255)", False, None),
            ("site_id",               "Integer",     False, "sites.id"),
            ("department",            "String(255)", True,  None),
            ("zone_classification",   "String(100)", True,  None),
            ("primary_hazard_id",     "Integer",     True,  "hazards.id"),
            ("staffing_requirement",  "Integer",     True,  None),
            ("equipment_list",        "Text",        True,  None),
            ("permit_types_required", "String(255)", True,  None),
            ("access_restrictions",   "String(255)", True,  None),
        ],
    ),
    (
        "employee", "Employee", "employees",
        [
            ("full_name",             "String(255)", False, None),
            ("date_of_birth",         "Date",        True,  None),
            ("gender",                "String(1)",   True,  None),
            ("employment_type",       "String(50)",  True,  None),
            ("employment_start_date", "Date",        True,  None),
            ("role_id",               "Integer",     True,  "roles.id"),
            ("department_id",         "Integer",     True,  "departments.id"),
            ("shift_pattern",         "String(50)",  True,  None),
            ("manager_id",            "Integer",     True,  "employees.id"),
            ("induction_date",        "Date",        True,  None),
            ("active_status",         "String(20)",  True,  None),
        ],
    ),
    (
        "permit_to_work", "PermitToWork", "permits_to_work",
        [
            ("permit_type_id",          "Integer",  False, "permit_types.id"),
            ("date_issued",             "Date",     False, None),
            ("time_issued",             "Time",     True,  None),
            ("location_station_id",     "Integer",  True,  "working_stations.id"),
            ("work_description",        "Text",     True,  None),
            ("duration_requested_hours","Integer",  True,  None),
            ("issued_by",               "Integer",  True,  "employees.id"),
            ("approved_by",             "Integer",  True,  "employees.id"),
            ("validity_start",          "DateTime", True,  None),
            ("validity_end",            "DateTime", True,  None),
            ("work_start_actual",       "DateTime", True,  None),
            ("work_end_actual",         "DateTime", True,  None),
            ("number_of_workers",       "Integer",  True,  None),
            ("status",                  "String(50)", True, None),
            ("deviation_reported",      "String(10)", True, None),
            ("incident_occurred",       "String(10)", True, None),
        ],
    ),
    (
        "incident", "Incident", "incidents",
        [
            ("report_date",             "Date",     True,  None),
            ("incident_date_time",      "DateTime", True,  None),
            ("location_station_id",     "Integer",  True,  "working_stations.id"),
            ("incident_type",           "String(100)", True, None),
            ("severity",                "String(50)",  True, None),
            ("number_persons_involved", "Integer",  True,  None),
            ("description",             "Text",     True,  None),
            ("immediate_cause",         "String(255)", True, None),
            ("root_cause",              "String(255)", True, None),
            ("hazard_id",               "Integer",  True,  "hazards.id"),
            ("permit_active",           "String(10)", True, None),
            ("control_failure",         "String(10)", True, None),
            ("reported_by",             "Integer",  True,  "employees.id"),
            ("investigation_status",    "String(50)", True, None),
            ("capa_generated",          "String(10)", True, None),
            ("days_away",               "Integer",  True,  None),
            ("root_cause_category",     "String(100)", True, None),
        ],
    ),
    (
        "near_miss", "NearMiss", "near_misses",
        [
            ("report_date",           "Date",     True, None),
            ("event_date_time",       "DateTime", True, None),
            ("location_station_id",   "Integer",  True, "working_stations.id"),
            ("description",           "Text",     True, None),
            ("potential_consequence", "String(255)", True, None),
            ("hazard_id",             "Integer",  True, "hazards.id"),
            ("underlying_cause",      "String(255)", True, None),
            ("control_failure",       "String(10)",  True, None),
            ("reported_by",           "Integer",  True, "employees.id"),
            ("capa_escalation",       "String(10)",  True, None),
        ],
    ),
    (
        "safety_walk", "SafetyWalk", "safety_walks",
        [
            ("inspection_date_time", "DateTime", True, None),
            ("location_station_id",  "Integer",  True, "working_stations.id"),
            ("inspector_id",         "Integer",  True, "employees.id"),
            ("inspection_type",      "String(100)", True, None),
            ("issues_found",         "Integer",  True, None),
            ("critical_issues",      "Integer",  True, None),
            ("housekeeping_rating",  "Integer",  True, None),
            ("compliance_rating",    "Integer",  True, None),
            ("follow_up_required",   "String(10)", True, None),
        ],
    ),
    (
        "capa_action", "CapaAction", "capa_actions",
        [
            ("incident_id",           "Integer",     True, "incidents.id"),
            ("action_type",           "String(100)", True, None),
            ("description",           "Text",        True, None),
            ("root_cause_addressed",  "String(255)", True, None),
            ("responsible_person_id", "Integer",     True, "employees.id"),
            ("due_date",              "Date",        True, None),
            ("status",                "String(50)",  True, None),
            ("effectiveness_rating",  "Integer",     True, None),
        ],
    ),
    (
        "shift_schedule", "ShiftSchedule", "shift_schedule",
        [
            ("employee_id",       "Integer",       False, "employees.id"),
            ("shift_date",        "Date",          False, None),
            ("shift_type",        "String(50)",    True,  None),
            ("shift_start",       "Time",          True,  None),
            ("shift_end",         "Time",          True,  None),
            ("actual_hours_worked", "Numeric(4,1)", True, None),
            ("station_id",        "Integer",       True,  "working_stations.id"),
            ("supervisor_id",     "Integer",       True,  "employees.id"),
        ],
    ),
]

SA_IMPORTS = {
    "String", "Integer", "Text", "Date", "DateTime", "Time",
    "Numeric", "Boolean", "ForeignKey", "Column",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  wrote  {path.relative_to(ROOT.parent)}")


def sa_type_imports(fields) -> str:
    used = set()
    for _, sa_type, _, fk in fields:
        base = sa_type.split("(")[0]
        used.add(base)
        if fk:
            used.add("ForeignKey")
    used.add("Column")
    return ", ".join(sorted(used & SA_IMPORTS))


# ---------------------------------------------------------------------------
# Model template
# ---------------------------------------------------------------------------
def gen_model(module, cls, table, fields) -> str:
    imports = sa_type_imports(fields)
    col_lines = []
    for col, sa_type, nullable, fk in fields:
        null_str = "" if not nullable else ", nullable=True"
        if fk:
            col_lines.append(
                f'    {col} = Column({sa_type}, ForeignKey("{fk}"){null_str})'
            )
        else:
            null_part = ", nullable=False" if not nullable else ""
            col_lines.append(
                f"    {col} = Column({sa_type}{null_part})"
            )
    cols = "\n".join(col_lines)
    return f'''from sqlalchemy import {imports}
from app.models.base import Base


class {cls}(Base):
    __tablename__ = "{table}"

{cols}
'''


# ---------------------------------------------------------------------------
# Schema template
# ---------------------------------------------------------------------------
PY_TYPE = {
    "String": "str", "Text": "str", "Date": "date",
    "DateTime": "datetime", "Time": "time", "Integer": "int",
    "Numeric": "Decimal", "Boolean": "bool", "Time": "time",
}

def sa_to_py(sa_type: str) -> str:
    base = sa_type.split("(")[0]
    return PY_TYPE.get(base, "Any")

def gen_schema(module, cls, fields) -> str:
    need = {"Optional", "datetime", "date", "time", "Decimal", "Any"}
    py_fields = [(col, sa_to_py(sa), nullable) for col, sa, nullable, _ in fields]
    used = {t for _, t, _ in py_fields} | {"Optional"}
    typing_imports = sorted(used & need)

    base_cols, create_cols, update_cols, resp_cols = [], [], [], []
    for col, py_type, nullable in py_fields:
        opt = f"Optional[{py_type}]" if nullable else py_type
        default = " = None" if nullable else ""
        base_cols.append(f"    {col}: {opt}{default}")
        update_cols.append(f"    {col}: Optional[{py_type}] = None")

    base_str   = "\n".join(base_cols)  or "    pass"
    update_str = "\n".join(update_cols) or "    pass"

    return f'''from __future__ import annotations
from typing import Optional, Any
from datetime import date, datetime, time
from decimal import Decimal
from pydantic import BaseModel
from app.schemas.base import TimestampMixin


class {cls}Base(BaseModel):
{base_str}


class {cls}Create({cls}Base):
    pass


class {cls}Update(BaseModel):
{update_str}


class {cls}Response({cls}Base, TimestampMixin):
    id: int

    model_config = {{"from_attributes": True}}
'''


# ---------------------------------------------------------------------------
# Repository template
# ---------------------------------------------------------------------------
def gen_repository(module, cls) -> str:
    return f'''from app.repositories.base import BaseRepository
from app.models.{module} import {cls}


class {cls}Repository(BaseRepository[{cls}]):
    model_class = {cls}
'''


# ---------------------------------------------------------------------------
# Service template
# ---------------------------------------------------------------------------
def gen_service(module, cls) -> str:
    return f'''from sqlalchemy.orm import Session
from app.repositories.{module} import {cls}Repository
from app.schemas.{module} import {cls}Create, {cls}Update
from app.core.exceptions import NotFoundError
from app.utils.logger import get_logger

logger = get_logger(__name__)


class {cls}Service:
    def __init__(self, db: Session) -> None:
        self._repo = {cls}Repository(db)

    def list(self, skip: int = 0, limit: int = 100):
        logger.debug("list {cls} skip=%s limit=%s", skip, limit)
        return self._repo.get_all(skip=skip, limit=limit)

    def get(self, id: int):
        item = self._repo.get_by_id(id)
        if item is None:
            raise NotFoundError("{cls}", id)
        return item

    def create(self, payload: {cls}Create):
        logger.info("create {cls}")
        return self._repo.create(payload.model_dump())

    def update(self, id: int, payload: {cls}Update):
        item = self._repo.update(id, payload.model_dump(exclude_unset=True))
        if item is None:
            raise NotFoundError("{cls}", id)
        logger.info("updated {cls} id=%s", id)
        return item

    def delete(self, id: int) -> None:
        if not self._repo.delete(id):
            raise NotFoundError("{cls}", id)
        logger.info("deleted {cls} id=%s", id)
'''


# ---------------------------------------------------------------------------
# Controller template
# ---------------------------------------------------------------------------
def gen_controller(module, cls, tag) -> str:
    return f'''from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.services.{module} import {cls}Service
from app.schemas.{module} import {cls}Create, {cls}Update, {cls}Response

router = APIRouter(prefix="/{tag}", tags=["{tag.replace("-", " ").title()}"])


def _svc(db: Session = Depends(get_db)) -> {cls}Service:
    return {cls}Service(db)


@router.get("/", response_model=list[{cls}Response])
def list_{module}s(skip: int = 0, limit: int = 100, svc: {cls}Service = Depends(_svc)):
    return svc.list(skip=skip, limit=limit)


@router.get("/{{id}}", response_model={cls}Response)
def get_{module}(id: int, svc: {cls}Service = Depends(_svc)):
    return svc.get(id)


@router.post("/", response_model={cls}Response, status_code=status.HTTP_201_CREATED)
def create_{module}(payload: {cls}Create, svc: {cls}Service = Depends(_svc)):
    return svc.create(payload)


@router.put("/{{id}}", response_model={cls}Response)
def update_{module}(id: int, payload: {cls}Update, svc: {cls}Service = Depends(_svc)):
    return svc.update(id, payload)


@router.delete("/{{id}}", status_code=status.HTTP_204_NO_CONTENT)
def delete_{module}(id: int, svc: {cls}Service = Depends(_svc)):
    svc.delete(id)
'''


# ---------------------------------------------------------------------------
# Generate all per-entity files
# ---------------------------------------------------------------------------
def scaffold():
    print("\n=== Scaffolding HSE backend ===\n")

    for module, cls, table, fields in ENTITIES:
        tag = module.replace("_", "-") + "s"

        write(ROOT / "models"       / f"{module}.py", gen_model(module, cls, table, fields))
        write(ROOT / "schemas"      / f"{module}.py", gen_schema(module, cls, fields))
        write(ROOT / "repositories" / f"{module}.py", gen_repository(module, cls))
        write(ROOT / "services"     / f"{module}.py", gen_service(module, cls))
        write(ROOT / "controllers"  / f"{module}.py", gen_controller(module, cls, tag))

    # __init__.py stubs for every package
    packages = ["", "config", "core", "models", "schemas",
                "repositories", "services", "controllers", "utils"]
    for pkg in packages:
        init = ROOT / pkg / "__init__.py" if pkg else ROOT / "__init__.py"
        if not init.exists():
            write(init, "")

    # logs dir
    logs = ROOT.parent / "logs"
    logs.mkdir(exist_ok=True)
    gitkeep = logs / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.touch()

    print("\n=== Done ===")


if __name__ == "__main__":
    scaffold()
