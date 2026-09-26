"""Bootstrap the 9 new role-based checklist templates into the DB."""
import json
import sys
sys.path.insert(0, '.')

from app.config.database import SessionLocal
from app.controllers.checklists import _default_templates
from sqlalchemy import text

db = SessionLocal()
templates = _default_templates()
count = 0
for t in templates:
    existing = db.execute(
        text('SELECT id FROM checklist_templates WHERE checklist_type = :ct'),
        {'ct': t['checklist_type']}
    ).first()
    if existing:
        continue
    db.execute(text("""
        INSERT INTO checklist_templates
        (checklist_type, display_name, submitter_roles, validator_roles, items_json, ui_json, sla_json)
        VALUES (:ct, :dn, :sr, :vr, :ij, :uj, :sj)
    """), {
        'ct': t['checklist_type'],
        'dn': t['display_name'],
        'sr': json.dumps(t['submitter_roles']),
        'vr': json.dumps(t['validator_roles']),
        'ij': json.dumps(t['items']),
        'uj': json.dumps(t.get('ui')) if t.get('ui') else None,
        'sj': json.dumps(t.get('sla')) if t.get('sla') else None,
    })
    count += 1

db.commit()
db.close()
print(f'Bootstrapped {count} new templates. Total now: {len(templates)}')
