"""Imports the client's own Module 5 (Contractors & Vendors) sample data —
SD_ContractorRegister, SD_ContractorInductions, SD_ContractorHours in
HSEIQ_Full_KPI_with_SampleData.xlsx — into the real WF-08 contractor registry
(contractor_companies, contractor_workers, contractor_hours) plus one current
ContractorScorecard per company so "Contractor Safety Score" has something to
average.

Every org gets its own copy of the same 16-company sample set, scoped by
organisation_id, matching how the rest of this app's demo data is org-scoped.
Additive and idempotent: an org already holding contractor_companies rows is
skipped entirely, so re-running is safe.

Usage (run from backend/ so the `app` package resolves):
    python scripts/import_module5_contractor_sample.py [path_to_xlsx]
"""
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl  # noqa: E402

from app.config.database import SessionLocal  # noqa: E402
from app.models.contractor import ContractorCompany, ContractorHours, ContractorScorecard, ContractorWorker  # noqa: E402
from app.models.organisation import Organisation  # noqa: E402
from app.services.hse_formulae import contractor_scorecard_verdict  # noqa: E402

DEFAULT_XLSX = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "HSEIQ_Full_KPI_with_SampleData.xlsx",
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
    companies = _rows(wb["SD_ContractorRegister"])
    inductions = _rows(wb["SD_ContractorInductions"])
    hours = _rows(wb["SD_ContractorHours"])
    employee_names = {r["Employee_ID"]: r["Full_Name"] for r in _rows(wb["Ref_Employees"])}

    db = SessionLocal()
    try:
        org_ids = [r.id for r in db.query(Organisation.id).order_by(Organisation.id).all()]
        for org_id in org_ids:
            if db.query(ContractorCompany).filter(ContractorCompany.organisation_id == org_id).first():
                print(f"org {org_id}: already has contractor companies, skipping")
                continue

            id_map = {}  # client's "CONT001" -> this org's new ContractorCompany.id
            for c in companies:
                row = ContractorCompany(
                    organisation_id=org_id,
                    company_name=c["Company_Name"],
                    service_type=c["Service_Type"],
                    contract_start_date=_d(c["Contract_Start_Date"]),
                    contract_end_date=_d(c["Contract_End_Date"]),
                    iso_45001_certified=1 if c["ISO_45001_Certified"] == "Yes" else 0,
                    last_safety_audit_date=_d(c["Last_Safety_Audit_Date"]),
                    # approved | conditional | barred | pending
                    prequalification_status="approved" if c["Prequalification_Status"] == "Approved" else "pending",
                    suspended=0 if c["Active_Y_N"] == "Yes" else 1,
                    source_system="import",
                    last_verified_at=datetime.now(),
                )
                db.add(row)
                db.flush()
                id_map[c["Contractor_ID"]] = row.id

                score = float(c["Safety_Performance_Score_0_100"])
                db.add(ContractorScorecard(
                    organisation_id=org_id,
                    contractor_company_id=row.id,
                    period_year=date.today().year,
                    period_quarter=(date.today().month - 1) // 3 + 1,
                    score=score,
                    incident_count=0,  # client's own M5 sample: 0 contractor incidents org-wide
                    permit_violations=0,
                    verdict=contractor_scorecard_verdict(score),
                    computed_at=datetime.now(),
                    source_system="import",
                    last_verified_at=datetime.now(),
                ))

            for i in inductions:
                company_id = id_map.get(i["Contractor_ID"])
                if company_id is None:
                    continue
                db.add(ContractorWorker(
                    organisation_id=org_id,
                    contractor_company_id=company_id,
                    full_name=employee_names.get(i["Employee_ID"], f"Contractor Worker {i['Employee_ID']}"),
                    badge_no=i["Employee_ID"],
                    trade=i["Induction_Type"],
                    induction_date=_d(i["Induction_Date"]),
                    induction_valid_until=_d(i["Induction_Expiry_Date"]),
                    site_access_status="granted" if i["Status"] == "Valid" else "pending",
                    source_system="import",
                    last_verified_at=datetime.now(),
                ))

            for h in hours:
                company_id = id_map.get(h["Contractor_ID"])
                if company_id is None:
                    continue
                db.add(ContractorHours(
                    organisation_id=org_id,
                    contractor_company_id=company_id,
                    period_year=h["Year"],
                    period_month=h["Month"],
                    hours_worked=h["Hours_Worked"],
                    source_system="import",
                    last_verified_at=datetime.now(),
                ))

            db.commit()
            print(f"org {org_id}: imported {len(companies)} companies, {len(inductions)} inductions, {len(hours)} hours rows")
    finally:
        db.close()


if __name__ == "__main__":
    main()
