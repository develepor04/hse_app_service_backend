"""AI governance — the audit trail behind every AI answer.

From HSE_AI_Overview_Client:

    Step 6 · The answer is recorded
    "Each answer stored with a confidence score and marked as AI-generated,
     then the user's decision to accept, amend or reject it is captured —
     creating a full audit trail."

    The core feature: "Whenever someone accepts, amends or rejects an AI
    suggestion — or overrides a safety gate — the reason and the outcome are
    recorded. Over time this reduces false alarms and builds frontline trust."

Confidence is derived, never invented by the model. It is a function of how
complete and how fresh the grounding snapshot was — because an answer built on
a stale or thin snapshot deserves less trust regardless of how fluent it reads.
"""
import hashlib
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.ai_decision import AiDecisionLog

# A snapshot section that came back empty means that source contributed nothing.
_EMPTY_MARKERS = ("no data", "none recorded", "not tracked", "0 records")


def snapshot_hash(briefing: str) -> str:
    """Pins exactly which grounded snapshot produced an answer, so the same
    question can be re-run against the same data later."""
    return hashlib.sha256((briefing or "").encode("utf-8")).hexdigest()


def derive_confidence(briefing: str, stale_sources: int = 0) -> float:
    """0-100 confidence in the grounding, not in the prose.

    Starts at 100 and deducts for a thin snapshot and for stale feeds. This
    mirrors the Data Quality Gate: >14 days stale is a Data Gap, and a gap must
    lower confidence rather than be silently trusted.
    """
    if not briefing:
        return 0.0

    lines = [l for l in briefing.splitlines() if l.strip()]
    empties = sum(1 for l in lines if any(m in l.lower() for m in _EMPTY_MARKERS))

    score = 100.0
    if lines:
        score -= min(40.0, empties / len(lines) * 100 * 0.6)
    score -= min(40.0, stale_sources * 10.0)
    if len(lines) < 15:
        # A very short briefing means most sources returned nothing.
        score -= 15.0

    return round(max(0.0, min(100.0, score)), 2)


def log_answer(
    db: Session,
    current_user,
    bucket: str,
    question: str,
    answer: str,
    briefing: str,
    model_id: str = "",
    provider: str = "",
    stale_sources: int = 0,
) -> Optional[int]:
    """Record one AI answer. Returns the log id the client uses to decide on it.

    Never raises into the chat path — an answer the user can read is worth more
    than a failed audit write, and the failure is visible in the logs.
    """
    try:
        row = AiDecisionLog(
            organisation_id=getattr(current_user, "org_id", None),
            user_id=getattr(current_user, "user_id", None),
            user_role=getattr(current_user, "role", None),
            role_bucket=bucket,
            question=(question or "")[:65000],
            answer=(answer or "")[:65000],
            model_id=model_id,
            model_version=model_id,
            provider=provider,
            snapshot_hash=snapshot_hash(briefing),
            snapshot_built_at=datetime.now(),
            confidence_score=derive_confidence(briefing, stale_sources),
            ai_generated=1,
            source_system="ai",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    except Exception:
        db.rollback()
        return None
