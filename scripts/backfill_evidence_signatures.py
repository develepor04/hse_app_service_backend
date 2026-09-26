"""One-time backfill for U-020: sign every already-stored /uploads/ URL.

save_image() now returns a signed URL (media_storage.sign_path) and the
serving route (app/main.py: serve_upload) refuses anything unsigned. Evidence
uploaded before that change has bare, unsigned paths in the columns below and
would 403 on next view without this.

Idempotent — a path that is already signed (has a `sig=` query string) is
left alone, so this is safe to re-run.

Usage:
    python scripts/backfill_evidence_signatures.py            # dry run — report only
    python scripts/backfill_evidence_signatures.py --apply    # actually rewrite rows
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.config.database import engine
from app.services.media_storage import sign_path

UPLOAD_PATH_RE = re.compile(r"^/uploads/[a-z0-9_]+/[a-zA-Z0-9_.-]+$")

# (table, column, "json_array" | "plain") — every column that can hold a
# /uploads/ path written by media_storage.save_image.
TARGETS = [
    ("audit_evidence", "file_url", "plain"),
    ("bowtie_barrier_verifications", "evidence_photos", "json_array"),
    ("bowtie_barrier_verifications", "evidence_docs", "json_array"),
    ("capa_evidence", "file_url", "plain"),
    ("checklist_submission_items", "evidence_json", "json_array"),
    ("hazards", "evidence_json", "json_array"),
    ("incidents", "evidence_json", "json_array"),
    ("near_misses", "evidence_json", "json_array"),
    ("permits_to_work", "evidence_json", "json_array"),
    ("psm_audit_findings", "evidence", "json_array"),
    ("psm_equipment_inspections", "photos", "json_array"),
    ("emergency_drills", "photos", "json_array"),
    ("risk_reports", "evidence_json", "json_array"),
    ("unsafe_acts", "evidence_json", "json_array"),
    ("training_records", "evidence_photo", "json_array"),
]


def _sign_if_unsigned(value: str) -> str:
    if "sig=" in value:
        return value  # already signed
    if not UPLOAD_PATH_RE.match(value):
        return value  # not one of our paths (or already has query params we don't recognise) — leave untouched
    return sign_path(value)


def _rewrite_json_array(raw: str) -> "str | None":
    try:
        items = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(items, list):
        return None
    changed = False
    new_items = []
    for item in items:
        if isinstance(item, str):
            signed = _sign_if_unsigned(item)
            changed = changed or (signed != item)
            new_items.append(signed)
        else:
            new_items.append(item)
    return json.dumps(new_items) if changed else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually rewrite rows. Without this, only reports the plan.")
    args = parser.parse_args()

    total_to_change = 0
    with engine.connect() as conn:
        for table, column, kind in TARGETS:
            try:
                rows = conn.execute(
                    text(f"SELECT id, `{column}` FROM `{table}` WHERE `{column}` LIKE '%/uploads/%'")
                ).fetchall()
            except Exception as exc:
                print(f"  SKIP  {table}.{column}  ({exc})")
                continue

            changes = []
            for row_id, raw in rows:
                if raw is None:
                    continue
                if kind == "json_array":
                    new_val = _rewrite_json_array(raw)
                else:
                    new_val = _sign_if_unsigned(raw)
                    new_val = new_val if new_val != raw else None
                if new_val is not None:
                    changes.append((row_id, new_val))

            if not changes:
                continue

            print(f"  {table}.{column}: {len(changes)} row(s) to sign")
            total_to_change += len(changes)
            if args.apply:
                for row_id, new_val in changes:
                    conn.execute(
                        text(f"UPDATE `{table}` SET `{column}` = :v WHERE id = :id"),
                        {"v": new_val, "id": row_id},
                    )
                conn.commit()

    if total_to_change == 0:
        print("Nothing to backfill — every stored evidence path is already signed.")
    elif not args.apply:
        print(f"\n{total_to_change} row(s) would be updated. Re-run with --apply to execute.")
    else:
        print(f"\nDone. {total_to_change} row(s) signed.")


if __name__ == "__main__":
    main()
