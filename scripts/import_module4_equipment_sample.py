"""Imports the client's own Module 4 (Assets & Operations) asset register —
Assets_Register in Assets_Sample_Data.xlsx — into the equipment table (see
app/models/equipment.py). Unlocks MTBF, PM Compliance (proxy), and SCE
Overdue Count on the Assets page.

Every org gets its own copy of the same 45-item sample set, scoped by
organisation_id, matching how the rest of this app's demo data is org-scoped
(see import_module5_contractor_sample.py for the same pattern).
Additive and idempotent: an org already holding equipment rows is skipped
entirely, so re-running is safe.

Usage (run from backend/ so the `app` package resolves):
    python scripts/import_module4_equipment_sample.py [path_to_xlsx]
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl  # noqa: E402

from app.config.database import SessionLocal  # noqa: E402
from app.models.equipment import Equipment  # noqa: E402
from app.models.organisation import Organisation  # noqa: E402

DEFAULT_XLSX = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "Assets_Sample_Data.xlsx",
)
XLSX_PATH = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_XLSX


def _rows(ws):
    all_rows = list(ws.iter_rows(values_only=True))
    header = all_rows[0]
    return [dict(zip(header, r)) for r in all_rows[1:]]


def _d(v):
    if v is None:
        return None
    return v.date() if isinstance(v, datetime) else v


def main():
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True)
    equipment_rows = _rows(wb["Assets_Register"])

    db = SessionLocal()
    try:
        org_ids = [r.id for r in db.query(Organisation.id).order_by(Organisation.id).all()]
        for org_id in org_ids:
            if db.query(Equipment).filter(Equipment.organisation_id == org_id).first():
                print(f"org {org_id}: already has equipment rows, skipping")
                continue

            for e in equipment_rows:
                db.add(Equipment(
                    organisation_id=org_id,
                    equipment_code=e["Equipment_ID"],
                    equipment_name=e["Equipment_Name"],
                    equipment_type=e["Equipment_Type"],
                    location_station=e["Location_Station"],
                    installation_date=_d(e["Installation_Date"]),
                    pm_interval_days=e["PM_Interval_Days"],
                    last_pm_date=_d(e["Last_PM_Date"]),
                    next_pm_due=_d(e["Next_PM_Due"]),
                    operating_hours_ytd=e["Operating_Hours_YTD"],
                    last_failure_date=_d(e["Last_Failure_Date"]),
                    mtbf_hours_estimated=e["MTBF_Hours_Estimated"],
                    safety_critical_sce=1 if e["Safety_Critical_SCE"] == "Yes" else 0,
                    status=e["Status"],
                    source_system="import",
                    last_verified_at=datetime.now(),
                ))

            db.commit()
            print(f"org {org_id}: imported {len(equipment_rows)} equipment rows")
    finally:
        db.close()


if __name__ == "__main__":
    main()
