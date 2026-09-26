"""Engine adapters — the bridge between capabilities and the code that serves them.

Each adapter takes the capability's input payload and returns an EngineOutput:
a result, a confidence score, and an explanation. The Orchestrator never calls a
service directly; it calls an adapter selected from the registry.

Confidence is produced per the spec's Section 3.1, which defines a different
mechanism for each tier:

  L2 Rules  all conditions met 1.0, partial 0.6-0.9, no match 0.0
  L6 LLM    grounding x consistency x schema, then a conservative x0.85

The Rules adapters below mostly return 1.0 or 0.0 — a deterministic formula
either resolved its inputs or it did not. That is correct and is the reason
>90% of traffic can auto-approve without a model.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from app.services import statutory_reporting
from app.services.capa_priority import prioritise
from app.services.hse_formulae import fatigue_index, rams_score
from app.services.incident_severity import classify_severity
from app.services.risk_scoring import score_risk


@dataclass
class EngineOutput:
    result: Any
    confidence: float
    explanation: str
    # Structured evidence for the explanation payload (Section 10). For a rules
    # engine this is the decision trace; for an LLM it would be grounding cites.
    supporting: Dict[str, Any] = field(default_factory=dict)


class EngineError(RuntimeError):
    """Engine could not produce a result. Triggers failover, not a retry."""


# ══════════════════════════════════════════════════════════════════════════════
# L2 · Rules Engine adapters
# ══════════════════════════════════════════════════════════════════════════════

def _rules_incident_severity(payload: Dict[str, Any]) -> EngineOutput:
    r = classify_severity(
        anyone_injured=bool(payload.get("anyone_injured")),
        treatment_level=payload.get("treatment_level"),
        days_away=payload.get("days_away"),
        dangerous_occurrence=bool(payload.get("dangerous_occurrence")),
        worst_case_fatal=bool(payload.get("worst_case_fatal")),
        recurring_event_type=bool(payload.get("recurring_event_type")),
    )
    # An unclassifiable incident is a genuine 0.0 — the tree could not decide,
    # so the Orchestrator escalates rather than auto-approving a guess.
    confidence = 1.0 if r.priority else 0.0
    return EngineOutput(
        result={
            "priority": r.priority, "label": r.label, "is_hipo": r.is_hipo,
            "is_recurring": r.is_recurring, "requires_systemic_rca": r.requires_systemic_rca,
            "investigation_days": r.investigation_days, "min_investigator": r.min_investigator,
        },
        confidence=confidence,
        explanation=r.explanation,
        supporting={"decision_trace": r.trace},
    )


def _rules_risk_score(payload: Dict[str, Any]) -> EngineOutput:
    r = score_risk(
        likelihood=payload.get("likelihood"),
        severity=payload.get("severity") or payload.get("consequence"),
        raw_score=payload.get("raw_score"),
        no_valid_rams=bool(payload.get("no_valid_rams")),
        new_worker=bool(payload.get("new_worker")),
        night_shift=bool(payload.get("night_shift")),
        temporary_control=bool(payload.get("temporary_control")),
    )
    return EngineOutput(
        result={
            "raw_score": r.raw_score, "adjusted_score": r.adjusted_score,
            "uplift_total": r.uplift_total, "band": r.band, "colour": r.colour,
            "review_frequency": r.review_frequency, "approval_route": r.approval_route,
            "blocks_work": r.blocks_work,
        },
        confidence=1.0 if r.adjusted_score is not None else 0.0,
        explanation=r.explanation,
        supporting={"uplifts_applied": r.uplifts_applied},
    )


def _rules_statutory(payload: Dict[str, Any]) -> EngineOutput:
    r = statutory_reporting.evaluate(
        payload.get("jurisdiction"),
        incident_at=payload.get("incident_at"),
        fatality=bool(payload.get("fatality")),
        injury_type=payload.get("injury_type"),
        days_away=payload.get("days_away"),
        dangerous_occurrence=bool(payload.get("dangerous_occurrence")),
        hospitalised=bool(payload.get("hospitalised")),
        hospitalised_over_24h=bool(payload.get("hospitalised_over_24h")),
        medical_treatment=bool(payload.get("medical_treatment")),
        loss_of_consciousness=bool(payload.get("loss_of_consciousness")),
        occupational_disease=bool(payload.get("occupational_disease")),
        permanent_disability=bool(payload.get("permanent_disability")),
        fire_or_explosion=bool(payload.get("fire_or_explosion")),
        major_construction=bool(payload.get("major_construction")),
        seveso_major_accident=bool(payload.get("seveso_major_accident")),
        royal_commission_site=bool(payload.get("royal_commission_site")),
        region=payload.get("region"),
    )
    # No jurisdiction means the rule could not be evaluated at all. That is a
    # partial match in Section 3.1 terms, not a confident "not reportable".
    confidence = 0.0 if not payload.get("jurisdiction") else 1.0
    # An obligation whose specific authority depends on a region we were not
    # given is a soft result: real, but not fully determined.
    if any(not o.encoded for o in r.obligations):
        confidence = 0.7
    return EngineOutput(
        result={
            "reportable": r.reportable,
            "obligations": [o.__dict__ for o in r.obligations],
            "earliest_due_at": r.earliest_due_at,
        },
        confidence=confidence,
        explanation=r.explanation,
    )


def _rules_capa_priority(payload: Dict[str, Any]) -> EngineOutput:
    r = prioritise(
        severity_potential=payload.get("severity_potential"),
        systemic_risk=payload.get("systemic_risk"),
        capa_type=payload.get("capa_type"),
        incident_priority=payload.get("incident_priority"),
        created_at=payload.get("created_at"),
    )
    # Scored and dated is a full match. One of the two missing is a partial.
    if r.priority_score is not None and r.capa_type:
        confidence = 1.0
    elif r.priority_score is not None or r.capa_type:
        confidence = 0.7
    else:
        confidence = 0.0
    return EngineOutput(
        result={
            "priority_score": r.priority_score, "priority_band": r.priority_band,
            "capa_type": r.capa_type, "capa_type_label": r.capa_type_label,
            "due_date": r.due_date, "evidence_required": r.evidence_required,
        },
        confidence=confidence,
        explanation=r.explanation,
    )


def _rules_fatigue(payload: Dict[str, Any]) -> EngineOutput:
    try:
        r = fatigue_index(
            shift_hours=float(payload.get("shift_hours") or 0),
            consecutive_days=int(payload.get("consecutive_days") or 0),
            night_shifts_7d=int(payload.get("night_shifts_7d") or 0),
        )
    except (TypeError, ValueError) as e:
        raise EngineError(f"fatigue inputs invalid: {e}")
    return EngineOutput(
        result={
            "fatigue_index": r.fatigue_index, "band": r.band,
            "requires_signoff": r.requires_signoff, "is_hard_block": r.is_hard_block,
        },
        confidence=1.0,
        explanation=r.explanation,
    )


def _rules_rams(payload: Dict[str, Any]) -> EngineOutput:
    criteria = payload.get("criteria") or {}
    if not criteria:
        raise EngineError("no RAMS criteria supplied")
    r = rams_score(**criteria)
    return EngineOutput(
        # Keyed "score" because CAP-RAMS-001's hitl_when reads r["score"] < 60.
        result={"score": r.total_score, "verdict": r.verdict, "criteria": r.criteria},
        confidence=1.0,
        explanation=r.explanation or f"RAMS total {r.total_score} -> {r.verdict}",
    )


# ══════════════════════════════════════════════════════════════════════════════
# L6 · LLM adapter
#
# Deliberately thin. The Orchestrator's job is to make sure this is reached
# rarely; the generation itself stays in app.controllers.ai where the grounding,
# streaming and provider handling already live.
# ══════════════════════════════════════════════════════════════════════════════

def _llm_generate(payload: Dict[str, Any]) -> EngineOutput:
    from app.config.settings import get_settings
    settings = get_settings()

    prompt = payload.get("prompt") or payload.get("text")
    if not prompt:
        raise EngineError("no prompt supplied for an LLM capability")

    key = getattr(settings, "anthropic_api_key", "") or getattr(settings, "azure_openai_api_key", "")
    if not key:
        # Not configured is an engine failure, so the chain falls through to
        # human review rather than the request appearing to succeed.
        raise EngineError("no LLM provider configured")

    from app.controllers.ai import _call_claude
    text = _call_claude(
        [{"role": "user", "content": prompt}],
        api_key=key,
        model=getattr(settings, "anthropic_model", "") or "claude-sonnet-4-6",
        base_url=getattr(settings, "anthropic_base_url", "") or "",
    )
    # Section 3.1: LLM confidence is grounding x consistency x schema, then a
    # conservative x0.85. Without grounding validation implemented we cannot
    # claim more than the floor, so this is capped at the multiplier itself —
    # which keeps every LLM result under the 0.90 auto-approve bar and routes it
    # to human review. That is the intended behaviour until Section 11.2 lands.
    return EngineOutput(
        result={"text": text},
        confidence=0.85,
        explanation="LLM generation. Grounding validation not implemented — "
                    "confidence capped at the conservative multiplier.",
    )


def _llm_chat(payload: Dict[str, Any]) -> EngineOutput:
    """Chat adapter with role-scoped briefings and conversation history.
    
    Payload structure:
        messages: list of conversation turns (required)
        db: SQLAlchemy session (required for briefing)
        current_user: CurrentUser dependency (required for role scoping)
        system_prompt: optional override for role prompt
        streaming: bool (if True, returns special streaming marker)
    """
    from app.config.settings import get_settings
    settings = get_settings()
    
    messages = payload.get("messages")
    if not messages:
        raise EngineError("no messages supplied for chat capability")
    
    db = payload.get("db")
    current_user = payload.get("current_user")
    if not db or not current_user:
        raise EngineError("chat requires db session and current_user context")
    
    # Import here to avoid circular dependency
    from app.controllers.ai import (
        _call_claude, _call_azure_openai, _prepare_request, _cached_briefing,
        _role_bucket, _ROLE_PROMPTS,
    )
    
    # Prepare the request with role-scoped briefing (reuses existing logic)
    bucket = _role_bucket(current_user)
    system_prompt = payload.get("system_prompt") or _ROLE_PROMPTS[bucket]
    briefing = _cached_briefing(db, current_user, bucket)

    # The briefing only carries org-level totals, so record-level questions ("the
    # last incident", "which site") used to hit a dead end. Appending the tool
    # guidance lets Claude decide to query instead — org_id is bound server-side
    # from the JWT, so the model can never widen its own scope.
    org_id = getattr(current_user, "org_id", None)
    if org_id is not None:
        from app.services import sql_agent
        system_prompt = system_prompt + sql_agent.chat_tool_guidance()

    # Prepend briefing as system message
    full_messages = [{"role": "system", "content": briefing}] + list(messages)

    # Check if streaming is requested
    if payload.get("streaming", False):
        # Return a special marker - streaming must be handled by the controller
        # since EngineOutput can't yield
        return EngineOutput(
            result={
                "streaming": True,
                "messages": full_messages,
                "system_prompt": system_prompt,
                "bucket": bucket,
                "org_id": org_id,
            },
            confidence=0.85,
            explanation="Chat request prepared for streaming (deferred to controller)",
        )
    
    # Blocking chat response
    last_error = None
    
    # Try Anthropic Claude first
    if settings.anthropic_api_key:
        try:
            text = _call_claude(
                full_messages,
                api_key=settings.anthropic_api_key,
                model=settings.anthropic_model,
                base_url=settings.anthropic_base_url or "",
                system_prompt=system_prompt,
                org_id=org_id,
            )
            return EngineOutput(
                result={
                    "text": text,
                    "model": settings.anthropic_model,
                    "provider": "anthropic",
                    "bucket": bucket,
                },
                confidence=0.85,
                explanation="Chat via Claude with role-scoped briefing. "
                           "Confidence capped at 0.85 (grounding validation not implemented).",
            )
        except Exception as e:
            last_error = e
    
    # Fallback to Azure OpenAI
    if settings.azure_openai_api_key and settings.azure_openai_endpoint:
        try:
            text = _call_azure_openai(full_messages, settings, system_prompt=system_prompt)
            return EngineOutput(
                result={
                    "text": text,
                    "model": getattr(settings, "azure_openai_deployment", "azure-openai"),
                    "provider": "azure_openai",
                    "bucket": bucket,
                },
                confidence=0.85,
                explanation="Chat via Azure OpenAI with role-scoped briefing. "
                           "Confidence capped at 0.85 (grounding validation not implemented).",
            )
        except Exception as e:
            last_error = e
    
    # Both failed or none configured
    if last_error:
        raise EngineError(f"All LLM providers failed: {last_error}")
    else:
        raise EngineError("No LLM provider configured")


# ══════════════════════════════════════════════════════════════════════════════

def _human_review(payload: Dict[str, Any]) -> EngineOutput:
    """L7 is terminal. It does not compute — it parks the request for a person."""
    return EngineOutput(
        result={"queued_for_human_review": True},
        confidence=1.0,
        explanation="Routed to the Human Review Queue. A person decides.",
    )


# capability_id -> {engine_id: handler}
ADAPTERS = {
    "CAP-INC-001":  {"RE-ENGINE-01": _rules_incident_severity},
    "CAP-RISK-001": {"RE-ENGINE-01": _rules_risk_score},
    "CAP-STAT-001": {"RE-ENGINE-01": _rules_statutory},
    "CAP-CAPA-001": {"RE-ENGINE-01": _rules_capa_priority},
    "CAP-FAT-001":  {"RE-ENGINE-01": _rules_fatigue},
    "CAP-RAMS-001": {"RE-ENGINE-01": _rules_rams, "LLM-ENGINE-01": _llm_generate},
    "CAP-DOC-001":  {"LLM-ENGINE-01": _llm_generate},
    "CAP-RCA-001":  {"LLM-ENGINE-01": _llm_generate},
    "CAP-CHAT-001": {"LLM-ENGINE-01": _llm_chat},
}

# Every capability can reach L7.
for _caps in ADAPTERS.values():
    _caps.setdefault("HR-ENGINE-01", _human_review)


def handler_for(capability_id: str, engine_id: str):
    """The adapter serving this capability at this engine, or None."""
    if engine_id == "HR-ENGINE-01":
        return _human_review
    return ADAPTERS.get(capability_id, {}).get(engine_id)
