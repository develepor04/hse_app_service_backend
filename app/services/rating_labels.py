"""Org-configurable wording for the rating vocabularies the client called out
by name in feedback: the quality scale (Excellent / Average / Below Average —
this app's own wording is Excellent / Good / Needs Improvement) and the risk
scale (Low / Medium / High Risk). Different industries read these words
differently, so an org admin can rename the bands and move the cutoffs from
Settings; everyone else keeps the current defaults unchanged.

Four separate scale_keys rather than one shared "quality"/"risk" pair: the
four call sites this feeds each already used their own numeric cutoffs before
this existed (e.g. compliance is 85/70, workforce competency is 80/60) —
collapsing them onto one shared scale would have silently moved one of the
two the first time this ran. Each keeps its own defaults; an admin can still
retune wording and thresholds per metric independently.

Stored in Organisation.formula_config["rating_labels"], next to the existing
contractor_score weights (see contractor_risk.py) — same JSON blob, same
merge-with-defaults pattern, no new table.
"""
from sqlalchemy.orm import Session

from app.models.organisation import Organisation

DEFAULT_RATING_LABELS = {
    # Ascending value = better.
    "workforce_competency": {
        "high_floor": 80, "high_label": "Excellent",
        "mid_floor": 60, "mid_label": "Good",
        "low_label": "Needs Improvement",
    },
    "compliance_score": {
        "high_floor": 85, "high_label": "Excellent",
        "mid_floor": 70, "mid_label": "Good",
        "low_label": "Needs Improvement",
    },
    # Ascending value = worse.
    "workforce_exposure_risk": {
        "high_floor": 30, "high_label": "High Risk",
        "mid_floor": 10, "mid_label": "Medium Risk",
        "low_label": "Low Risk",
    },
    "asset_maintenance_risk": {
        "high_floor": 60, "high_label": "High Risk",
        "mid_floor": 25, "mid_label": "Medium Risk",
        "low_label": "Low Risk",
    },
}

# "quality" scales: high band = good = green. "risk" scales: high band = bad
# = red. Tone follows whichever band the value actually landed in, not a
# separate hardcoded threshold — so a relabelled/re-thresholded band still
# gets the right colour after an admin edits it in Settings.
_QUALITY_TONES = ("green", "amber", "red")
_RISK_TONES = ("red", "amber", "green")
_TONE_BY_SCALE = {
    "workforce_competency": _QUALITY_TONES,
    "compliance_score": _QUALITY_TONES,
    "workforce_exposure_risk": _RISK_TONES,
    "asset_maintenance_risk": _RISK_TONES,
}


def get_rating_labels(db: Session, org_id) -> dict:
    """Per-org band config for every scale, merged over the defaults so a
    partially-saved override (e.g. only one scale customised) still yields
    complete bands for the rest."""
    saved = None
    if org_id:
        org = db.query(Organisation).filter(Organisation.id == org_id).first()
        if org and org.formula_config:
            saved = org.formula_config.get("rating_labels")
    return {
        scale: {**defaults, **((saved or {}).get(scale) or {})}
        for scale, defaults in DEFAULT_RATING_LABELS.items()
    }


def label_and_tone(value: float, labels: dict, scale_key: str) -> tuple[str, str]:
    """Resolve (label, tone) for `value` against `labels[scale_key]` — the
    dict returned by get_rating_labels(), or DEFAULT_RATING_LABELS directly."""
    cfg = labels[scale_key]
    tones = _TONE_BY_SCALE[scale_key]
    if value >= cfg["high_floor"]:
        return cfg["high_label"], tones[0]
    if value >= cfg["mid_floor"]:
        return cfg["mid_label"], tones[1]
    return cfg["low_label"], tones[2]
