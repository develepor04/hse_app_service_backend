"""WF-05 · the checklist templates every audit runs from.

"Maintains the checklist templates every audit runs from" — the Admin, on the
web console. Until now those templates were literal dicts in the audit
controller, which meant the sentence could not be true: there was nothing to
maintain and no screen could have shown it.

Two rules shape this module:

  · **Templates are versioned, never rewritten.** An audit conducted last
    quarter was run against the template as it stood then. Editing it in place
    would change the record of what was asked, months after it was asked.

  · **The built-in templates stay as a fallback.** An organisation that has never
    opened the templates screen still gets a real checklist, because an auditor
    standing in front of a site with an empty checklist is a far worse failure
    than a generic one.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.audit import AuditChecklistTemplate, AuditChecklistTemplateItem
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Built-in fallbacks
# ══════════════════════════════════════════════════════════════════════════════
#
# `is_critical` marks the items where a zero is an automatic Major NC and an
# instant alert. `section` is load-bearing: a section scoring below 60% raises a
# Minor NC of its own, so how items are grouped changes what the audit finds.

BUILTIN_GENERIC = [
    {"section": "PPE & People", "title": "PPE Compliance", "clause": "ISO 45001 8.1",
     "question": "Are all personnel wearing the required PPE for this area?", "is_critical": True},
    {"section": "PPE & People", "title": "Competence on Task", "clause": "ISO 45001 7.2",
     "question": "Can workers explain the hazards of their task and show a valid competence card?"},
    {"section": "Housekeeping", "title": "Walkways & Egress", "clause": "ISO 45001 8.1",
     "question": "Are walkways, exits and work areas clear of hazards and debris?"},
    {"section": "Emergency", "title": "Emergency Readiness", "clause": "ISO 45001 8.2",
     "question": "Are fire extinguishers, alarms and exits accessible and in date?", "is_critical": True},
    {"section": "Plant & Equipment", "title": "Equipment Guarding", "clause": "ISO 45001 8.1",
     "question": "Are moving parts and machinery properly guarded?", "is_critical": True},
    {"section": "Documentation", "title": "Permits & Records", "clause": "ISO 45001 8.1.2",
     "question": "Are permits, SOPs and inspection records available and current?"},
]

BUILTIN_BY_TYPE = {
    "safety management system": [
        {"section": "Leadership", "title": "Policy & Objectives", "clause": "ISO 45001 5.2",
         "question": "Is the HSE policy documented, signed and communicated?"},
        {"section": "Planning", "title": "Risk Assessments", "clause": "ISO 45001 6.1.2",
         "question": "Are current risk assessments in place for all key activities?", "is_critical": True},
        {"section": "Support", "title": "Training Records", "clause": "ISO 45001 7.2",
         "question": "Are competency and induction records complete and up to date?"},
        {"section": "Operation", "title": "Incident Management", "clause": "ISO 45001 10.2",
         "question": "Are incidents investigated with corrective actions closed out?"},
        {"section": "Performance", "title": "Management Review", "clause": "ISO 45001 9.3",
         "question": "Has a management review been conducted within the period?"},
    ],
    "fire safety": [
        {"section": "Detection & Suppression", "title": "Extinguishers", "clause": "OSHA 1910.157",
         "question": "Are extinguishers present, charged and inspected?", "is_critical": True},
        {"section": "Egress", "title": "Exit Routes", "clause": "ISO 45001 8.2",
         "question": "Are emergency exits unobstructed and clearly signed?", "is_critical": True},
        {"section": "Detection & Suppression", "title": "Alarm System", "clause": "ISO 45001 8.2",
         "question": "Was the fire alarm tested and functional?"},
        {"section": "Egress", "title": "Emergency Lighting", "clause": "ISO 45001 8.2",
         "question": "Is emergency lighting operational on all routes?"},
    ],
    "environmental": [
        {"section": "Aspects & Impacts", "title": "Aspect Register", "clause": "ISO 14001 6.1.2",
         "question": "Is the environmental aspects register current and complete?"},
        {"section": "Waste", "title": "Waste Segregation", "clause": "ISO 14001 8.1",
         "question": "Is waste segregated, labelled and stored per the consent conditions?"},
        {"section": "Spill Control", "title": "Bunding & Spill Kits", "clause": "ISO 14001 8.2",
         "question": "Are bunds intact and spill kits present, stocked and in date?", "is_critical": True},
        {"section": "Monitoring", "title": "Discharge Monitoring", "clause": "ISO 14001 9.1",
         "question": "Are discharge and emission monitoring records complete and within limits?"},
    ],
}


# The type name the generic fallback answers to. `seed_builtins` writes it as
# the default template, so the two must agree.
BUILTIN_GENERIC_TYPE = "General"


def builtin_types() -> List[dict]:
    """The checklist types that work with no maintained template behind them.

    Shipped to the console so the scheduling form can offer a choice before an
    organisation has seeded any template. Hard-coding the same four names in the
    frontend would have them disagree the day a built-in is added here — and the
    list is what `resolve` actually falls back to, so it should come from the
    same module.
    """
    return [{"key": BUILTIN_GENERIC_TYPE, "label": BUILTIN_GENERIC_TYPE}] + [
        {"key": k.title(), "label": k.title()} for k in BUILTIN_BY_TYPE
    ]


# ══════════════════════════════════════════════════════════════════════════════
# Reading
# ══════════════════════════════════════════════════════════════════════════════

def items_of(db: Session, template_id: int) -> List[AuditChecklistTemplateItem]:
    return (
        db.query(AuditChecklistTemplateItem)
        .filter(AuditChecklistTemplateItem.template_id == template_id)
        .order_by(AuditChecklistTemplateItem.seq.asc(), AuditChecklistTemplateItem.id.asc())
        .all()
    )


def list_templates(
    db: Session, org_id: Optional[int], include_inactive: bool = False,
) -> List[AuditChecklistTemplate]:
    q = db.query(AuditChecklistTemplate).filter(
        AuditChecklistTemplate.organisation_id == org_id
    )
    if not include_inactive:
        q = q.filter(AuditChecklistTemplate.is_active.is_(True))
    return q.order_by(
        AuditChecklistTemplate.checklist_type.asc(),
        AuditChecklistTemplate.version.desc(),
    ).all()


def resolve(
    db: Session, org_id: Optional[int], checklist_type: Optional[str],
) -> tuple[Optional[AuditChecklistTemplate], List[dict]]:
    """The template an audit of this type should be seeded from.

    Returns (template_or_None, items). A None template means the built-in
    fallback was used — the caller records `template_id = None`, which is a
    truthful statement that no maintained template covered this audit type.

    Matching is by substring on `checklist_type` rather than exact equality,
    because an audit titled "Q3 Fire Safety — Nacelle Line" should find the
    "Fire Safety" template. Highest version wins.
    """
    key = (checklist_type or "").strip().lower()

    candidates = (
        db.query(AuditChecklistTemplate)
        .filter(
            AuditChecklistTemplate.organisation_id == org_id,
            AuditChecklistTemplate.is_active.is_(True),
        )
        .order_by(AuditChecklistTemplate.version.desc())
        .all()
    )

    if key:
        for t in candidates:
            t_key = (t.checklist_type or "").strip().lower()
            if t_key and (t_key in key or key in t_key):
                return t, _as_dicts(items_of(db, t.id))

    for t in candidates:
        if t.is_default:
            return t, _as_dicts(items_of(db, t.id))

    # Nothing maintained covers this. Fall back rather than hand the auditor an
    # empty checklist.
    for k, items in BUILTIN_BY_TYPE.items():
        if k in key:
            return None, [dict(i) for i in items]
    return None, [dict(i) for i in BUILTIN_GENERIC]


def _as_dicts(items: List[AuditChecklistTemplateItem]) -> List[dict]:
    return [
        {
            "section": i.section, "title": i.title, "question": i.question,
            "clause": i.clause, "is_critical": bool(i.is_critical),
        }
        for i in items
    ]


# ══════════════════════════════════════════════════════════════════════════════
# Writing
# ══════════════════════════════════════════════════════════════════════════════

def create(
    db: Session, org_id: Optional[int], user_id: Optional[int], *,
    name: str, checklist_type: Optional[str], description: Optional[str],
    standard: Optional[str], is_default: bool, items: List[dict],
) -> AuditChecklistTemplate:
    t = AuditChecklistTemplate(
        organisation_id=org_id,
        name=name,
        checklist_type=checklist_type,
        description=description,
        standard=standard,
        version=1,
        is_active=True,
        is_default=is_default,
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(t)
    db.flush()
    _write_items(db, t.id, items)
    if is_default:
        _clear_other_defaults(db, org_id, t.id)
    return t


def new_version(
    db: Session, template: AuditChecklistTemplate, user_id: Optional[int], *,
    name: Optional[str] = None, checklist_type: Optional[str] = None,
    description: Optional[str] = None, standard: Optional[str] = None,
    is_default: Optional[bool] = None, items: Optional[List[dict]] = None,
) -> AuditChecklistTemplate:
    """Supersede a template rather than edit it.

    The old version is deactivated, not deleted: audits already conducted point
    at it, and the report has to be able to say what was actually asked.
    """
    latest = (
        db.query(AuditChecklistTemplate)
        .filter(
            AuditChecklistTemplate.organisation_id == template.organisation_id,
            AuditChecklistTemplate.checklist_type == template.checklist_type,
        )
        .order_by(AuditChecklistTemplate.version.desc())
        .first()
    )
    next_version = (latest.version if latest else template.version) + 1

    fresh = AuditChecklistTemplate(
        organisation_id=template.organisation_id,
        name=name if name is not None else template.name,
        checklist_type=checklist_type if checklist_type is not None else template.checklist_type,
        description=description if description is not None else template.description,
        standard=standard if standard is not None else template.standard,
        version=next_version,
        is_active=True,
        is_default=template.is_default if is_default is None else is_default,
        created_by=template.created_by,
        updated_by=user_id,
    )
    db.add(fresh)
    db.flush()

    _write_items(
        db, fresh.id,
        items if items is not None else _as_dicts(items_of(db, template.id)),
    )

    template.is_active = False
    template.updated_by = user_id
    if fresh.is_default:
        _clear_other_defaults(db, fresh.organisation_id, fresh.id)

    logger.info(
        "Template %s superseded by v%s (%s)", template.id, next_version, fresh.id,
    )
    return fresh


def _write_items(db: Session, template_id: int, items: List[dict]) -> None:
    for n, i in enumerate(items, start=1):
        db.add(AuditChecklistTemplateItem(
            template_id=template_id,
            seq=i.get("seq") or n,
            section=i.get("section") or "General",
            title=(i.get("title") or "Checklist item")[:255],
            question=i.get("question"),
            clause=i.get("clause"),
            is_critical=bool(i.get("is_critical")),
        ))


def _clear_other_defaults(db: Session, org_id: Optional[int], keep_id: int) -> None:
    (
        db.query(AuditChecklistTemplate)
        .filter(
            AuditChecklistTemplate.organisation_id == org_id,
            AuditChecklistTemplate.id != keep_id,
            AuditChecklistTemplate.is_default.is_(True),
        )
        .update({"is_default": False}, synchronize_session=False)
    )


def seed_builtins(db: Session, org_id: Optional[int], user_id: Optional[int]) -> int:
    """Import the built-in templates so the Admin has something to edit.

    Idempotent by checklist_type: running it twice does not produce two Fire
    Safety templates.
    """
    existing = {
        (t.checklist_type or "").strip().lower()
        for t in db.query(AuditChecklistTemplate).filter(
            AuditChecklistTemplate.organisation_id == org_id
        ).all()
    }
    created = 0

    for key, items in BUILTIN_BY_TYPE.items():
        if key in existing:
            continue
        create(
            db, org_id, user_id,
            name=key.title(), checklist_type=key.title(), description=None,
            standard=items[0].get("clause", "").split()[0] if items else None,
            is_default=False, items=items,
        )
        created += 1

    if "general" not in existing:
        create(
            db, org_id, user_id,
            name="General Site Inspection", checklist_type="General",
            description="Used when no template matches the audit type.",
            standard="ISO 45001", is_default=True, items=BUILTIN_GENERIC,
        )
        created += 1

    return created
