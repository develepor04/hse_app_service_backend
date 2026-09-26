"""
Seed realistic HSE data into hse_db so the dashboard shows live numbers.
Run: python seed_data.py
Safe to re-run — skips tables that already have rows.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pymysql
from datetime import date, datetime, timedelta
import random

from app.config.settings import get_settings

_s = get_settings()
conn = pymysql.connect(host=_s.db_host, port=_s.db_port, user=_s.db_user, password=_s.db_password, database=_s.db_name)
cur = conn.cursor()

def count(table):
    cur.execute(f"SELECT COUNT(*) FROM `{table}`")
    return cur.fetchone()[0]

def skip(table):
    n = count(table)
    if n:
        print(f"  skip  {table} ({n} rows already)")
        return True
    return False

today = date.today()

# ─── 1. Organisation ──────────────────────────────────────────────────────────
if not skip("organisation"):
    cur.execute("""
        INSERT INTO organisation
            (organisation_name, country, industry_sector, number_of_employees,
             headquarters_location, iso_45001_status, regulatory_authority, establishment_date)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, ("NexGen Industrial Ltd", "United Kingdom", "Manufacturing & Construction",
          420, "Leeds, West Yorkshire", "Certified", "HSE UK", "2005-03-12"))
    conn.commit()
    print("  done  organisation")

# ─── 2. Hazard Categories ─────────────────────────────────────────────────────
if not skip("hazard_categories"):
    cats = [
        ("Chemical Exposure",   "Exposure to hazardous chemical substances"),
        ("Mechanical Hazards",  "Risks from machinery, moving parts, pressure systems"),
        ("Electrical Hazards",  "Live electrical systems, arc flash, shock risk"),
        ("Fire & Explosion",    "Ignition sources, flammable materials, gas leaks"),
        ("Working at Height",   "Falls from elevated platforms, ladders, scaffolding"),
        ("Manual Handling",     "Musculoskeletal risks from lifting and carrying"),
        ("Noise & Vibration",   "Excessive noise exposure and hand-arm vibration"),
    ]
    cur.executemany(
        "INSERT INTO hazard_categories (category_name, description) VALUES (%s,%s)", cats)
    conn.commit()
    print("  done  hazard_categories")

# Fetch category IDs
cur.execute("SELECT id, category_name FROM hazard_categories")
cat_map = {name: id_ for id_, name in cur.fetchall()}

# ─── 3. Hazards ───────────────────────────────────────────────────────────────
if not skip("hazards"):
    hazards = [
        (cat_map["Chemical Exposure"],  "Solvent Vapour Inhalation",     "High",   "Probable"),
        (cat_map["Chemical Exposure"],  "Acid Splash to Skin/Eyes",       "Critical","Possible"),
        (cat_map["Mechanical Hazards"], "Unguarded Rotating Parts",       "High",   "Likely"),
        (cat_map["Mechanical Hazards"], "Struck by Falling Object",       "Critical","Possible"),
        (cat_map["Electrical Hazards"], "Exposed Live Conductors",        "Critical","Unlikely"),
        (cat_map["Electrical Hazards"], "Overloaded Circuit / Arc Flash", "High",   "Possible"),
        (cat_map["Fire & Explosion"],   "Flammable Liquid Storage",       "Critical","Possible"),
        (cat_map["Fire & Explosion"],   "Hot Work Near Combustibles",     "High",   "Likely"),
        (cat_map["Working at Height"],  "Unsecured Scaffold Boards",      "Critical","Possible"),
        (cat_map["Working at Height"],  "Ladder Slip / Fall",             "High",   "Probable"),
        (cat_map["Manual Handling"],    "Heavy Lift Without Aid",         "Medium", "Likely"),
        (cat_map["Noise & Vibration"],  "Prolonged Pneumatic Tool Use",   "Medium", "Likely"),
    ]
    cur.executemany(
        "INSERT INTO hazards (category_id, hazard_name, severity, probability) VALUES (%s,%s,%s,%s)",
        hazards)
    conn.commit()
    print("  done  hazards")

cur.execute("SELECT id FROM hazards ORDER BY id")
hazard_ids = [r[0] for r in cur.fetchall()]

# ─── 4. Sites ─────────────────────────────────────────────────────────────────
if not skip("sites"):
    sites = [
        ("Leeds Main Plant",       "Industrial Estate, Kirkstall Rd", "LS4 2AX", "Leeds",     "Manufacturing", "Operational", 12, 300, "Steel Components",  "High"),
        ("Bradford Warehouse",     "Canal Rd, Bradford",              "BD1 4AA", "Bradford",  "Warehouse",     "Operational",  6, 150, "Storage & Dispatch", "Medium"),
        ("Sheffield Construction", "Meadowhall Rd, Sheffield",        "S9 1EJ",  "Sheffield", "Construction",  "Operational",  8, 200, "Civil Engineering",  "High"),
    ]
    cur.executemany("""
        INSERT INTO sites
            (site_name, address, postcode, city, type, operational_status,
             number_of_working_stations, capacity, primary_products, hazard_classification)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, sites)
    conn.commit()
    print("  done  sites")

cur.execute("SELECT id FROM sites ORDER BY id")
site_ids = [r[0] for r in cur.fetchall()]
s1, s2, s3 = site_ids[0], site_ids[1], site_ids[2]

# ─── 5. Permit Types ─────────────────────────────────────────────────────────
if not skip("permit_types"):
    ptypes = [
        ("Hot Work Permit",             "High",   8,  2),
        ("Working at Height Permit",    "High",   12, 4),
        ("Confined Space Entry Permit", "Critical",4, 1),
        ("Electrical Isolation Permit", "High",   8,  2),
        ("Excavation Permit",           "Medium", 24, 3),
    ]
    cur.executemany(
        "INSERT INTO permit_types (permit_type_name, risk_level, validity_period_hours, concurrent_limit) VALUES (%s,%s,%s,%s)",
        ptypes)
    conn.commit()
    print("  done  permit_types")

cur.execute("SELECT id FROM permit_types ORDER BY id")
ptype_ids = [r[0] for r in cur.fetchall()]

# ─── 6. Roles ─────────────────────────────────────────────────────────────────
if not skip("roles"):
    roles = [
        ("HSE Manager",     "Management",  9, "Yes", "Yes"),
        ("Safety Officer",  "Safety",      7, "Yes", "Yes"),
        ("Site Supervisor", "Operations",  6, "Yes", "No"),
        ("Site Inspector",  "Inspection",  5, "No",  "Yes"),
        ("Maintenance Tech","Engineering", 4, "No",  "No"),
        ("Warehouse Operative","Operations",3,"No",  "No"),
        ("Civil Engineer",  "Engineering", 6, "Yes", "No"),
    ]
    cur.executemany("""
        INSERT INTO roles (role_name, job_category, authority_level, permit_authority, safety_signatory)
        VALUES (%s,%s,%s,%s,%s)
    """, roles)
    conn.commit()
    print("  done  roles")

cur.execute("SELECT id FROM roles ORDER BY id")
role_ids = [r[0] for r in cur.fetchall()]
r_mgr, r_safety, r_sup, r_insp, r_tech, r_wh, r_eng = role_ids

# ─── 7. Departments (manager_id=NULL first) ───────────────────────────────────
if not skip("departments"):
    depts = [
        (s1, "HSE & Compliance"),
        (s1, "Production Floor"),
        (s1, "Maintenance"),
        (s2, "Warehouse Operations"),
        (s2, "Logistics & Dispatch"),
        (s3, "Civil Works"),
        (s3, "Structural Engineering"),
    ]
    cur.executemany(
        "INSERT INTO departments (site_id, department_name, manager_id, number_of_teams) VALUES (%s,%s,NULL,%s)",
        [(s, n, 3) for s, n in depts])
    conn.commit()
    print("  done  departments")

cur.execute("SELECT id FROM departments ORDER BY id")
dept_ids = [r[0] for r in cur.fetchall()]
d_hse, d_prod, d_maint, d_wh, d_log, d_civil, d_struct = dept_ids

# ─── 8. Working Stations ──────────────────────────────────────────────────────
if not skip("working_stations"):
    stations = [
        ("Assembly Line A",      s1, "Production Floor",  "Zone-B", hazard_ids[2], 8,  "Lathe, Press, Conveyor",     "Hot Work", "PPE Mandatory"),
        ("Welding Bay 1",        s1, "Production Floor",  "Zone-A", hazard_ids[7], 4,  "MIG Welder, Angle Grinder",  "Hot Work", "Hot Work Zone"),
        ("Chemical Store Room",  s1, "HSE & Compliance",  "Zone-C", hazard_ids[0], 2,  "Storage Racks, Eyewash",     "None",     "Restricted"),
        ("Roof Access Platform", s1, "Maintenance",       "Zone-A", hazard_ids[8], 3,  "Scaffold, Safety Harness",   "WAH",      "Height > 2m"),
        ("Electrical Substation",s1, "Maintenance",       "Zone-D", hazard_ids[4], 2,  "HV Panel, Transformers",     "Electrical","Authorised Only"),
        ("Pallet Bay North",     s2, "Warehouse Ops",     "Zone-A", hazard_ids[10],6,  "Forklift, Pallet Trucks",    "None",     "Hi-Vis Required"),
        ("Loading Dock 1",       s2, "Logistics",         "Zone-B", hazard_ids[3], 4,  "Dock Leveller, Tail Lift",   "None",     "Banksman Required"),
        ("Scaffold Level 3",     s3, "Civil Works",       "Zone-A", hazard_ids[8], 6,  "Scaffold, Power Tools",      "WAH",      "Height > 6m"),
        ("Excavation Trench A",  s3, "Civil Works",       "Zone-B", hazard_ids[3], 5,  "Excavator, Shoring",         "Excavation","Trench Support"),
        ("Steel Frame Bay",      s3, "Structural Eng",    "Zone-C", hazard_ids[2], 8,  "Crane, Steel Beams",         "WAH",      "Crane Zone"),
    ]
    cur.executemany("""
        INSERT INTO working_stations
            (station_name, site_id, department, zone_classification, primary_hazard_id,
             staffing_requirement, equipment_list, permit_types_required, access_restrictions)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, stations)
    conn.commit()
    print("  done  working_stations")

cur.execute("SELECT id FROM working_stations ORDER BY id")
ws_ids = [r[0] for r in cur.fetchall()]

# ─── 9. Employees ─────────────────────────────────────────────────────────────
if not skip("employees"):
    emp_data = [
        # (full_name, dob, gender, emp_type, start_date, role_id, dept_id, shift, active)
        ("Sarah Mitchell",   "1978-04-15", "F", "Permanent", "2010-06-01", r_mgr,   d_hse,    "Day",   "Active"),
        ("James Patel",      "1985-09-22", "M", "Permanent", "2015-03-15", r_safety, d_hse,   "Day",   "Active"),
        ("Emma Clarke",      "1990-11-08", "F", "Permanent", "2018-07-10", r_insp,  d_hse,    "Day",   "Active"),
        ("Raj Sharma",       "1982-02-28", "M", "Permanent", "2012-01-20", r_sup,   d_prod,   "Day",   "Active"),
        ("Tom Bradley",      "1975-07-14", "M", "Permanent", "2008-09-05", r_tech,  d_maint,  "Night", "Active"),
        ("Aisha Rahman",     "1993-05-30", "F", "Permanent", "2020-02-17", r_safety, d_prod,  "Day",   "Active"),
        ("Kevin O'Brien",    "1980-12-03", "M", "Permanent", "2013-08-22", r_sup,   d_maint,  "Day",   "Active"),
        ("Priya Nair",       "1988-03-19", "F", "Permanent", "2017-04-11", r_insp,  d_wh,     "Day",   "Active"),
        ("Marcus Williams",  "1979-08-25", "M", "Permanent", "2009-05-14", r_wh,    d_wh,     "Day",   "Active"),
        ("Lisa Chen",        "1991-01-07", "F", "Contract",  "2023-01-09", r_wh,    d_log,    "Day",   "Active"),
        ("David Singh",      "1986-06-18", "M", "Permanent", "2014-11-03", r_eng,   d_civil,  "Day",   "Active"),
        ("Natalie Foster",   "1984-10-12", "F", "Permanent", "2016-06-28", r_eng,   d_struct, "Day",   "Active"),
        ("Ahmed Hassan",     "1977-03-22", "M", "Permanent", "2007-02-15", r_sup,   d_civil,  "Day",   "Active"),
        ("Sophie Turner",    "1995-09-14", "F", "Contract",  "2022-09-01", r_tech,  d_maint,  "Day",   "Active"),
        ("Daniel Brown",     "1983-04-09", "M", "Permanent", "2011-07-30", r_tech,  d_prod,   "Shift", "Active"),
    ]
    cur.executemany("""
        INSERT INTO employees
            (full_name, date_of_birth, gender, employment_type, employment_start_date,
             role_id, department_id, shift_pattern, active_status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, emp_data)
    conn.commit()
    print("  done  employees")

cur.execute("SELECT id FROM employees ORDER BY id")
emp_ids = [r[0] for r in cur.fetchall()]
# Named references
e_mgr   = emp_ids[0]   # Sarah Mitchell - HSE Manager
e_safety= emp_ids[1]   # James Patel
e_insp  = emp_ids[2]   # Emma Clarke
e_sup1  = emp_ids[3]   # Raj Sharma
e_tech1 = emp_ids[4]   # Tom Bradley
e_safety2=emp_ids[5]   # Aisha Rahman
e_sup2  = emp_ids[6]   # Kevin O'Brien
e_insp2 = emp_ids[7]   # Priya Nair
e_wh1   = emp_ids[8]   # Marcus Williams
e_wh2   = emp_ids[9]   # Lisa Chen
e_eng1  = emp_ids[10]  # David Singh
e_eng2  = emp_ids[11]  # Natalie Foster
e_sup3  = emp_ids[12]  # Ahmed Hassan
e_tech2 = emp_ids[13]  # Sophie Turner
e_tech3 = emp_ids[14]  # Daniel Brown

# Update dept managers now that employees exist
cur.execute("UPDATE departments SET manager_id=%s WHERE id=%s", (e_mgr,  d_hse))
cur.execute("UPDATE departments SET manager_id=%s WHERE id=%s", (e_sup1, d_prod))
cur.execute("UPDATE departments SET manager_id=%s WHERE id=%s", (e_sup2, d_maint))
cur.execute("UPDATE departments SET manager_id=%s WHERE id=%s", (e_insp2,d_wh))
cur.execute("UPDATE departments SET manager_id=%s WHERE id=%s", (e_wh1,  d_log))
cur.execute("UPDATE departments SET manager_id=%s WHERE id=%s", (e_sup3, d_civil))
cur.execute("UPDATE departments SET manager_id=%s WHERE id=%s", (e_eng2, d_struct))
conn.commit()

# ─── 10. Permits to Work ──────────────────────────────────────────────────────
if not skip("permits_to_work"):
    now = datetime.now()
    permits = [
        # (ptype_id, date_issued, station_id, description, duration, issued_by, approved_by, v_start, v_end, workers, status)
        (ptype_ids[0], today,           ws_ids[1], "Welding repair on conveyor bracket",    8,  e_safety, e_mgr,   now - timedelta(hours=2), now + timedelta(hours=6), 2, "Active"),
        (ptype_ids[1], today,           ws_ids[3], "Roof membrane inspection",              12, e_safety, e_mgr,   now - timedelta(hours=1), now + timedelta(hours=11),3, "Active"),
        (ptype_ids[3], today,           ws_ids[4], "HV panel maintenance",                  8, e_tech1,  e_mgr,   now - timedelta(hours=3), now + timedelta(hours=5), 1, "Active"),
        (ptype_ids[4], today,           ws_ids[8], "Excavation for drainage pipe",          24, e_eng1,   e_sup3,  now - timedelta(hours=4), now + timedelta(hours=20),5, "Active"),
        (ptype_ids[1], today,           ws_ids[9], "Steel beam lifting operation",          12, e_eng1,   e_sup3,  now - timedelta(hours=1), now + timedelta(hours=11),6, "Active"),
        (ptype_ids[0], today - timedelta(days=1), ws_ids[0], "Welding on assembly jig",    8,  e_safety, e_mgr,   now - timedelta(days=1), now - timedelta(hours=16),2, "Completed"),
        (ptype_ids[2], today - timedelta(days=2), ws_ids[4], "Tank cleaning - confined space", 4, e_tech1, e_mgr, now - timedelta(days=2), now - timedelta(days=2, hours=-4), 2, "Completed"),
        (ptype_ids[1], today - timedelta(days=1), ws_ids[7], "Scaffold erection Level 3",  12, e_eng1,   e_sup3,  now - timedelta(days=1), now - timedelta(hours=13),4, "Completed"),
        (ptype_ids[0], today + timedelta(days=1), ws_ids[1], "Pipe welding in boiler room", 8, e_safety2,e_mgr,  now + timedelta(days=1), now + timedelta(days=1, hours=8), 3, "Pending"),
        (ptype_ids[3], today + timedelta(days=2), ws_ids[4], "Cable installation EV bay",   8, e_tech2,  e_mgr,  now + timedelta(days=2), now + timedelta(days=2, hours=8), 2, "Pending"),
    ]
    cur.executemany("""
        INSERT INTO permits_to_work
            (permit_type_id, date_issued, location_station_id, work_description,
             duration_requested_hours, issued_by, approved_by,
             validity_start, validity_end, number_of_workers, status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, permits)
    conn.commit()
    print("  done  permits_to_work")

# ─── 11. Incidents ────────────────────────────────────────────────────────────
if not skip("incidents"):
    incidents = [
        # recent incidents — last 90 days, varied severity
        (today - timedelta(days=3),  "Chemical Exposure",   "Significant", 1, "Solvent splash during decanting",       "Inadequate PPE",       "Poor procedure",       hazard_ids[1], "Yes", "Yes", e_safety,  "Under Investigation", "Yes"),
        (today - timedelta(days=7),  "Fall from Height",    "Critical",    2, "Operative fell from scaffold board",    "Unsecured platform",   "Training gap",         hazard_ids[8], "No",  "Yes", e_insp,    "Completed",           "Yes"),
        (today - timedelta(days=11), "Mechanical",          "High",        1, "Hand caught in unguarded press",        "Guard removed",        "Supervision failure",  hazard_ids[2], "Yes", "Yes", e_sup1,    "Completed",           "Yes"),
        (today - timedelta(days=14), "Fire",                "High",        0, "Small fire near solvent store",         "Ignition source",      "Flammable storage",    hazard_ids[6], "No",  "Yes", e_safety,  "Completed",           "Yes"),
        (today - timedelta(days=18), "Electrical",          "Critical",    1, "Electric shock from exposed cable",     "Cable damaged",        "Maintenance backlog",  hazard_ids[4], "No",  "Yes", e_tech1,   "Under Investigation", "Yes"),
        (today - timedelta(days=22), "Manual Handling",     "Low",         1, "Back strain lifting 30kg component",    "No manual aid used",   "Training gap",         hazard_ids[10],"No",  "No",  e_sup1,    "Completed",           "No"),
        (today - timedelta(days=25), "Chemical Exposure",   "Significant", 2, "Gas leak in chemical store room",       "Valve failure",        "Equipment age",        hazard_ids[0], "No",  "Yes", e_mgr,     "Completed",           "Yes"),
        (today - timedelta(days=30), "Fall from Height",    "High",        1, "Near-fatal ladder slip on roof",        "Wet surface",          "Inadequate access",    hazard_ids[9], "No",  "Yes", e_insp,    "Completed",           "Yes"),
        (today - timedelta(days=35), "Mechanical",          "Low",         1, "Minor laceration from sheet metal",     "Sharp edge unmarked",  "Housekeeping",         hazard_ids[2], "No",  "No",  e_sup1,    "Completed",           "No"),
        (today - timedelta(days=40), "Noise",               "Low",         3, "Hearing complaint from drill operators","No ear protection",    "PPE compliance",       hazard_ids[11],"No",  "No",  e_safety2, "Completed",           "No"),
        (today - timedelta(days=45), "Fire",                "High",        0, "Hot work ignited oil residue",          "Inadequate isolation", "Procedure not followed",hazard_ids[7],"Yes","Yes", e_safety,  "Completed",           "Yes"),
        (today - timedelta(days=50), "Electrical",          "Significant", 1, "Arc flash during panel switching",      "LOTO not applied",     "System failure",       hazard_ids[5], "No",  "Yes", e_tech1,   "Completed",           "Yes"),
        (today - timedelta(days=55), "Fall from Height",    "Critical",    1, "Fall from excavation edge",             "No edge protection",   "Site condition",       hazard_ids[8], "No",  "Yes", e_eng1,    "Completed",           "Yes"),
        (today - timedelta(days=60), "Mechanical",          "Significant", 2, "Forklift struck pedestrian",            "Unmarked crossing",    "Traffic management",   hazard_ids[2], "No",  "Yes", e_insp2,   "Completed",           "Yes"),
        (today - timedelta(days=70), "Chemical Exposure",   "High",        1, "Chlorine exposure during tank clean",   "Confined space entry", "Permit bypassed",      hazard_ids[0], "No",  "Yes", e_mgr,     "Completed",           "Yes"),
        (today - timedelta(days=75), "Manual Handling",     "Low",         2, "Repetitive strain injury claim",        "Workstation ergonomics","Poor design",         hazard_ids[10],"No",  "No",  e_sup2,    "Completed",           "No"),
        (today - timedelta(days=80), "Fire",                "Significant", 0, "Electrical fire in switchroom",         "Overloaded circuit",   "Maintenance backlog",  hazard_ids[5], "No",  "Yes", e_tech1,   "Completed",           "Yes"),
        (today - timedelta(days=85), "Fall from Height",    "High",        1, "Worker slipped off edge beam",          "No fall arrest",       "Equipment failure",    hazard_ids[8], "No",  "Yes", e_eng1,    "Completed",           "Yes"),
        (today - timedelta(days=2),  "Mechanical",          "Significant", 1, "Crush injury — door mechanism",         "Faulty door sensor",   "Equipment defect",     hazard_ids[2], "No",  "Yes", e_sup1,    "Under Investigation", "Yes"),
        (today - timedelta(days=1),  "Chemical Exposure",   "High",        1, "Acid mist during battery charging",     "Ventilation failed",   "Maintenance gap",      hazard_ids[1], "Yes", "Yes", e_safety2, "Open",                "No"),
    ]
    rows = []
    ws_cycle = [ws_ids[0], ws_ids[1], ws_ids[2], ws_ids[3], ws_ids[7], ws_ids[8], ws_ids[9]]
    for i, inc in enumerate(incidents):
        dt, itype, sev, n_persons, desc, imm_cause, root_cause, haz_id, permit_active, ctrl_fail, rep_by, inv_status, capa_gen = inc
        ws = ws_cycle[i % len(ws_cycle)]
        rows.append((
            dt, datetime.combine(dt, datetime.min.time()).replace(hour=random.randint(7,16), minute=random.randint(0,59)),
            ws, itype, sev, n_persons, desc, imm_cause, root_cause,
            haz_id, permit_active, ctrl_fail, rep_by, inv_status, capa_gen
        ))
    cur.executemany("""
        INSERT INTO incidents
            (report_date, incident_date_time, location_station_id, incident_type, severity,
             number_persons_involved, description, immediate_cause, root_cause, hazard_id,
             permit_active, control_failure, reported_by, investigation_status, capa_generated)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, rows)
    conn.commit()
    print("  done  incidents")

cur.execute("SELECT id FROM incidents ORDER BY id")
inc_ids = [r[0] for r in cur.fetchall()]

# ─── 12. Near Misses ──────────────────────────────────────────────────────────
if not skip("near_misses"):
    nms = [
        (today - timedelta(days=1),  ws_ids[7], "Near miss — operatives almost hit by falling scaffold clip during dismantling", "Fatal crush injury",      hazard_ids[8],  "Equipment failure",     "No",  e_insp,   "Yes"),
        (today - timedelta(days=2),  ws_ids[1], "Welder's mask not in place briefly when arc struck",                            "Eye injury / arc burn",   hazard_ids[7],  "Complacency",           "No",  e_sup1,   "No"),
        (today - timedelta(days=4),  ws_ids[8], "Excavation edge collapse — worker stepped back in time",                        "Burial / suffocation",    hazard_ids[3],  "Unstable ground",       "Yes", e_eng1,   "Yes"),
        (today - timedelta(days=5),  ws_ids[4], "Unauthorised entry into live HV substation",                                    "Fatal electrocution",     hazard_ids[4],  "Signage inadequate",    "Yes", e_tech1,  "Yes"),
        (today - timedelta(days=6),  ws_ids[2], "Chemical drum fell from racking — narrowly missed worker",                      "Chemical burn / fatality",hazard_ids[0],  "Overloaded racking",    "Yes", e_safety, "Yes"),
        (today - timedelta(days=8),  ws_ids[5], "Forklift near-miss with pedestrian at loading dock entrance",                   "Crush injury",            hazard_ids[3],  "No segregation",        "No",  e_insp2,  "No"),
        (today - timedelta(days=9),  ws_ids[3], "Harness clip not engaged — worker noticed at edge",                             "Fatal fall",              hazard_ids[8],  "Pre-use check failure", "Yes", e_insp,   "Yes"),
        (today - timedelta(days=10), ws_ids[0], "Loose belt guard on lathe — vibration caused partial detachment",               "Severe laceration",       hazard_ids[2],  "Maintenance gap",       "No",  e_tech3,  "No"),
        (today - timedelta(days=12), ws_ids[1], "Hot work permit expired mid-task — operator continued",                         "Fire or explosion",       hazard_ids[7],  "Permit management",     "Yes", e_safety, "Yes"),
        (today - timedelta(days=15), ws_ids[9], "Crane slew zone not cordoned — worker walked under load",                       "Fatal struck-by",         hazard_ids[3],  "Poor planning",         "Yes", e_eng2,   "Yes"),
        (today - timedelta(days=18), ws_ids[6], "Tail lift failed to lock — pallet slid",                                        "Crush / fall",            hazard_ids[2],  "Equipment defect",      "No",  e_wh1,    "No"),
        (today - timedelta(days=20), ws_ids[2], "Solvent container left open overnight — vapour build-up",                       "Fire / inhalation",       hazard_ids[0],  "Housekeeping lapse",    "No",  e_safety2,"No"),
        (today - timedelta(days=22), ws_ids[8], "Excavation — shoring boards not installed per plan",                            "Collapse / burial",       hazard_ids[3],  "Supervision gap",       "Yes", e_sup3,   "Yes"),
        (today - timedelta(days=25), ws_ids[4], "LOTO tag missing from isolation point",                                         "Electrocution",           hazard_ids[4],  "Procedure not followed","Yes", e_tech1,  "Yes"),
        (today - timedelta(days=28), ws_ids[7], "Worker caught foot on scaffold tie — nearly fell 4m",                           "Serious fall injury",     hazard_ids[8],  "Housekeeping",          "No",  e_insp,   "No"),
    ]
    rows = []
    for nm in nms:
        rep_date, ws, desc, potential, haz_id, cause, ctrl_fail, rep_by, capa_esc = nm
        evt_dt = datetime.combine(rep_date, datetime.min.time()).replace(hour=random.randint(7,17))
        rows.append((rep_date, evt_dt, ws, desc, potential, haz_id, cause, ctrl_fail, rep_by, capa_esc))
    cur.executemany("""
        INSERT INTO near_misses
            (report_date, event_date_time, location_station_id, description, potential_consequence,
             hazard_id, underlying_cause, control_failure, reported_by, capa_escalation)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, rows)
    conn.commit()
    print("  done  near_misses")

# ─── 13. Safety Walks (last 35 days for compliance trend chart) ───────────────
if not skip("safety_walks"):
    sw_rows = []
    inspectors = [e_insp, e_insp2, e_safety, e_safety2, e_mgr]
    stations   = [ws_ids[0], ws_ids[1], ws_ids[3], ws_ids[5], ws_ids[7], ws_ids[8], ws_ids[9]]
    itypes     = ["Planned Inspection", "Unannounced Audit", "Daily Walk", "PPE Check", "Compliance Audit"]
    for day_offset in range(35, -1, -1):
        d = today - timedelta(days=day_offset)
        # 1-2 walks per day
        for _ in range(random.randint(1, 2)):
            hr  = random.randint(8, 15)
            ws  = random.choice(stations)
            ins = random.choice(inspectors)
            itype = random.choice(itypes)
            issues  = random.randint(0, 5)
            critical= random.randint(0, min(issues, 2))
            hk_rating  = random.randint(3, 5)
            comp_rating = random.randint(3, 5)
            follow_up = "Yes" if critical > 0 or issues >= 3 else "No"
            sw_rows.append((
                datetime(d.year, d.month, d.day, hr, random.randint(0,59)),
                ws, ins, itype, issues, critical, hk_rating, comp_rating, follow_up
            ))
    cur.executemany("""
        INSERT INTO safety_walks
            (inspection_date_time, location_station_id, inspector_id, inspection_type,
             issues_found, critical_issues, housekeeping_rating, compliance_rating, follow_up_required)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, sw_rows)
    conn.commit()
    print(f"  done  safety_walks ({len(sw_rows)} rows)")

# ─── 14. CAPA Actions ─────────────────────────────────────────────────────────
# The legacy CAPA seed block inserted synthetic incident-linked rows that look
# like live data but were actually demo fixtures. Keep the table empty here so
# the dashboard only shows records created from the real application flow.
if not skip("capa_actions"):
    print("  skip  capa_actions (legacy demo rows removed; use live CAPA creation)")

cur.close()
conn.close()
print("\nAll done. Restart your backend server and refresh the dashboard.")
