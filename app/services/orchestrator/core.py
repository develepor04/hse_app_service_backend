"""The AI Orchestrator — deterministic engine selection over the LEAN hierarchy.

Source: EHSERA AI Platform Enterprise Architecture ISMS v1.0, Sections 1
(Orchestrator), 3 (Confidence Framework) and 10 (Explainability).

The Orchestrator is NOT an AI. It is a rule-governed process controller. Section
1.4 is explicit: "The Orchestrator does not use AI to select engines — the
selection process itself must be transparent and auditable."

It enforces three things that individual workflow code cannot be trusted to
enforce for itself:

  1. no engine above the minimum capable tier is invoked
  2. every decision is auditable and replayable
  3. HITL gates are never bypassed regardless of engine confidence

Request lifecycle (Section 1.2), condensed to what this platform can honour:

    resolve capability -> select engine (LEAN traversal) -> invoke
      -> evaluate confidence -> decision pathway -> audit record
"""
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.services.orchestrator import engines as engine_adapters
from app.services.orchestrator.registry import (
    Capability, Engine, HEALTH_OK, HUMAN_ENGINE,
    default_capabilities, default_engines,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Decision pathways (Section 3.2)
# ══════════════════════════════════════════════════════════════════════════════

AUTO_APPROVE = "AUTO_APPROVE"
HUMAN_REVIEW = "HUMAN_REVIEW"
ESCALATE = "ESCALATE"
AUTO_REJECT = "AUTO_REJECT"

ESCALATION_FLOOR = 0.40   # below this the spec escalates rather than queues


@dataclass
class OrchestratorResult:
    capability_id: str
    capability_version: str
    result: Any
    confidence: float
    threshold: float
    pathway: str
    engine_selected: Optional[str]
    engines_tried: List[str] = field(default_factory=list)
    engines_skipped: List[Dict[str, str]] = field(default_factory=list)
    explanation: str = ""
    requires_hitl: bool = False
    hitl_reason: Optional[str] = None
    hitl_sla_minutes: Optional[int] = None
    hitl_due_at: Optional[datetime] = None
    latency_ms: int = 0
    cost: float = 0.0
    correlation_id: Optional[str] = None
    input_hash: Optional[str] = None
    supporting: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "capability_version": self.capability_version,
            "result": self.result,
            "confidence": round(self.confidence, 4),
            "threshold": self.threshold,
            "pathway": self.pathway,
            "engine_selected": self.engine_selected,
            "engines_tried": self.engines_tried,
            "engines_skipped": self.engines_skipped,
            "explanation": self.explanation,
            "requires_hitl": self.requires_hitl,
            "hitl_reason": self.hitl_reason,
            "hitl_sla_minutes": self.hitl_sla_minutes,
            "hitl_due_at": self.hitl_due_at.isoformat() if self.hitl_due_at else None,
            "latency_ms": self.latency_ms,
            "cost": self.cost,
            "correlation_id": self.correlation_id,
            "input_hash": self.input_hash,
            "supporting": self.supporting,
        }


class UnknownCapability(KeyError):
    pass


# ══════════════════════════════════════════════════════════════════════════════
# Circuit breaker (Section 1.5)
#
#   CLOSED -> OPEN at >=20% failures in a 60s window or 3 consecutive timeouts
#   OPEN -> HALF_OPEN after 30s, one probe
# ══════════════════════════════════════════════════════════════════════════════

CLOSED, OPEN, HALF_OPEN = "CLOSED", "OPEN", "HALF_OPEN"


class CircuitBreaker:
    WINDOW_SECONDS = 60
    FAILURE_RATE = 0.20
    CONSECUTIVE_TIMEOUTS = 3
    RECOVERY_SECONDS = 30

    def __init__(self):
        self._events: Dict[str, List[tuple]] = {}    # engine_id -> [(ts, ok)]
        self._state: Dict[str, str] = {}
        self._opened_at: Dict[str, float] = {}
        self._consecutive: Dict[str, int] = {}

    def state(self, engine_id: str) -> str:
        st = self._state.get(engine_id, CLOSED)
        if st == OPEN and time.time() - self._opened_at.get(engine_id, 0) >= self.RECOVERY_SECONDS:
            self._state[engine_id] = HALF_OPEN
            return HALF_OPEN
        return st

    def allows(self, engine_id: str) -> bool:
        """HALF_OPEN allows exactly the probe; the caller records the outcome."""
        return self.state(engine_id) != OPEN

    def record(self, engine_id: str, ok: bool) -> None:
        now = time.time()
        events = [e for e in self._events.get(engine_id, []) if now - e[0] <= self.WINDOW_SECONDS]
        events.append((now, ok))
        self._events[engine_id] = events

        if ok:
            self._consecutive[engine_id] = 0
            if self.state(engine_id) == HALF_OPEN:
                self._state[engine_id] = CLOSED
            return

        self._consecutive[engine_id] = self._consecutive.get(engine_id, 0) + 1
        if self.state(engine_id) == HALF_OPEN:
            self._trip(engine_id)
            return

        failures = sum(1 for _, k in events if not k)
        if self._consecutive[engine_id] >= self.CONSECUTIVE_TIMEOUTS or (
            len(events) >= 5 and failures / len(events) >= self.FAILURE_RATE
        ):
            self._trip(engine_id)

    def _trip(self, engine_id: str) -> None:
        self._state[engine_id] = OPEN
        self._opened_at[engine_id] = time.time()
        logger.warning("Circuit breaker OPEN for engine %s", engine_id)

    def force_open(self, engine_id: str) -> None:
        """Section 1.5 FORCED-OPEN — maintenance or model rollback."""
        self._trip(engine_id)

    def reset(self, engine_id: str) -> None:
        self._state[engine_id] = CLOSED
        self._consecutive[engine_id] = 0
        self._events[engine_id] = []


# ══════════════════════════════════════════════════════════════════════════════

def _hash_input(payload: Dict[str, Any]) -> str:
    """SHA-256 of the input. Section 1.2 stores the hash, never the raw data."""
    try:
        blob = json.dumps(payload, sort_keys=True, default=str)
    except (TypeError, ValueError):
        blob = repr(sorted(payload.items()))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class Orchestrator:
    """Routes a capability request down the LEAN hierarchy.

    Stateless with respect to business data. The circuit breaker and the result
    cache are per-process; the spec puts both in Redis, which is a deployment
    change rather than a logic change.
    """

    def __init__(self, capabilities=None, engines=None, breaker=None, audit_sink=None):
        self.capabilities: Dict[str, Capability] = capabilities or default_capabilities()
        self.engines: Dict[str, Engine] = engines or default_engines()
        self.breaker = breaker or CircuitBreaker()
        # Called with an OrchestratorResult after every decision. The controller
        # supplies one that writes to the audit table.
        self.audit_sink = audit_sink
        self._cache: Dict[str, tuple] = {}       # (input_hash, cap_id) -> (expires, result)

        # Attach handlers so Engine.available reflects what can actually run.
        for cap_id, by_engine in engine_adapters.ADAPTERS.items():
            for engine_id in by_engine:
                if engine_id in self.engines and self.engines[engine_id].handler is None:
                    self.engines[engine_id].handler = True   # marker: serviceable

    # ── Selection ────────────────────────────────────────────────────────────
    def _chain(self, cap: Capability) -> List[str]:
        """Preferred engine first, then the declared fallbacks. L7 always last."""
        chain = [cap.preferred_engine] + [e for e in cap.fallback_chain if e != cap.preferred_engine]
        if HUMAN_ENGINE not in chain:
            chain.append(HUMAN_ENGINE)
        return chain

    def _skip_reason(self, cap: Capability, engine_id: str, spent: float) -> Optional[str]:
        """Why this engine cannot serve the request — None means it can."""
        engine = self.engines.get(engine_id)
        if engine is None:
            return "not in engine registry"
        if engine.health != HEALTH_OK:
            return f"health {engine.health}"
        if engine_adapters.handler_for(cap.capability_id, engine_id) is None:
            return "no adapter for this capability"
        if not self.breaker.allows(engine_id):
            return "circuit breaker OPEN"
        # Section 1.4 step 4 — cost budget. Human review is never priced out.
        if engine_id != HUMAN_ENGINE and spent + engine.cost_per_call > cap.cost_limit_per_call:
            return (f"cost {engine.cost_per_call:.3f} would exceed "
                    f"limit {cap.cost_limit_per_call:.3f}")
        return None

    # ── Invocation ───────────────────────────────────────────────────────────
    def invoke(
        self,
        capability_id: str,
        payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
        use_cache: bool = True,
        audit_sink=None,
    ) -> OrchestratorResult:
        """`audit_sink` is per-call on purpose. The Orchestrator is a process-wide
        singleton, so a request-scoped sink assigned to the instance would be
        visible to every concurrent request and write audit rows against the
        wrong user."""
        cap = self.capabilities.get(capability_id)
        if cap is None:
            raise UnknownCapability(capability_id)

        started = time.perf_counter()
        input_hash = _hash_input(payload)
        cache_key = (input_hash, capability_id)

        # Section 12.2 exact cache. Never cache a human-review outcome — the
        # queue entry is per-request, not a reusable answer.
        if use_cache and cap.cache_ttl_seconds > 0:
            hit = self._cache.get(cache_key)
            if hit and hit[0] > time.time():
                cached = hit[1]
                logger.debug("cache hit for %s", capability_id)
                return cached

        tried: List[str] = []
        skipped: List[Dict[str, str]] = []
        spent = 0.0
        output = None
        engine_used = None
        # The best score any *computing* engine managed. L7 reports 1.0 by
        # definition (Section 3.1: a human decision is the terminal arbiter),
        # which must not be mistaken for the request having been answered
        # confidently — see _decide.
        best_real_confidence = 0.0

        for engine_id in self._chain(cap):
            reason = self._skip_reason(cap, engine_id, spent)
            if reason:
                skipped.append({"engine": engine_id, "reason": reason})
                continue

            handler = engine_adapters.handler_for(cap.capability_id, engine_id)
            tried.append(engine_id)
            try:
                candidate = handler(payload)
                self.breaker.record(engine_id, ok=True)
            except engine_adapters.EngineError as e:
                self.breaker.record(engine_id, ok=False)
                skipped.append({"engine": engine_id, "reason": f"engine error: {e}"})
                continue
            except Exception as e:                      # noqa: BLE001 — failover is the point
                self.breaker.record(engine_id, ok=False)
                logger.exception("engine %s raised for %s", engine_id, capability_id)
                skipped.append({"engine": engine_id, "reason": f"unhandled error: {e}"})
                continue

            spent += self.engines[engine_id].cost_per_call
            output, engine_used = candidate, engine_id
            if engine_id != HUMAN_ENGINE:
                best_real_confidence = max(best_real_confidence, candidate.confidence)

            # Good enough to stop descending. Below threshold we keep going —
            # that is the fallback chain doing its job.
            if candidate.confidence >= cap.confidence_threshold:
                break

        latency_ms = int((time.perf_counter() - started) * 1000)

        if output is None:
            result = OrchestratorResult(
                capability_id=cap.capability_id, capability_version=cap.version,
                result=None, confidence=0.0, threshold=cap.confidence_threshold,
                pathway=ESCALATE, engine_selected=None, engines_tried=tried,
                engines_skipped=skipped, latency_ms=latency_ms, cost=spent,
                correlation_id=correlation_id, input_hash=input_hash,
                explanation="No engine in the chain could serve this capability.",
                requires_hitl=True, hitl_reason="all engines exhausted",
                hitl_sla_minutes=cap.sla_minutes,
                hitl_due_at=datetime.utcnow() + timedelta(minutes=cap.sla_minutes),
            )
            self._audit(result, audit_sink)
            return result

        result = self._decide(cap, output, engine_used, tried, skipped,
                              latency_ms, spent, correlation_id, input_hash,
                              best_real_confidence)

        if use_cache and cap.cache_ttl_seconds > 0 and result.pathway == AUTO_APPROVE:
            self._cache[cache_key] = (time.time() + cap.cache_ttl_seconds, result)

        self._audit(result, audit_sink)
        return result

    # ── Confidence evaluation and pathway (Section 3.2) ──────────────────────
    def _decide(self, cap, output, engine_used, tried, skipped,
                latency_ms, spent, correlation_id, input_hash,
                best_real_confidence=0.0) -> OrchestratorResult:
        landed_on_human = engine_used == HUMAN_ENGINE

        # Section 3.1 gives Human Review confidence 1.0 because a human decision
        # is the terminal arbiter. That is a statement about the *human's*
        # verdict, not about the request. If the chain fell through to L7 the
        # question is still unanswered, so report the best score a computing
        # engine actually achieved — otherwise a capability no engine could
        # serve would auto-approve a payload that only says "queued".
        confidence = best_real_confidence if landed_on_human else output.confidence

        # HITL is decided BEFORE the confidence pathway, because Section 1 makes
        # it non-negotiable: a mandatory gate is never bypassed by a high score.
        hitl, hitl_reason = False, None
        if cap.requires_hitl:
            hitl, hitl_reason = True, "capability requires human-in-the-loop"
        elif cap.hitl_when:
            try:
                if cap.hitl_when(output.result):
                    hitl, hitl_reason = True, "result met the capability's mandatory-review condition"
            except Exception:                            # noqa: BLE001
                # A broken predicate must fail safe — toward review, not past it.
                hitl, hitl_reason = True, "mandatory-review condition could not be evaluated"

        # Landing on L7 is never an auto-approval, whatever the numbers say.
        if landed_on_human:
            pathway = ESCALATE if confidence < ESCALATION_FLOOR else HUMAN_REVIEW
            hitl = True
            hitl_reason = hitl_reason or (
                "no computing engine could serve this capability — routed to human review")
        elif confidence < ESCALATION_FLOOR:
            pathway = ESCALATE
            hitl, hitl_reason = True, hitl_reason or f"confidence {confidence:.2f} below escalation floor"
        elif confidence < cap.confidence_threshold:
            pathway = HUMAN_REVIEW
            hitl, hitl_reason = True, hitl_reason or (
                f"confidence {confidence:.2f} below threshold {cap.confidence_threshold:.2f}")
        elif hitl:
            pathway = HUMAN_REVIEW
        else:
            pathway = AUTO_APPROVE

        sla = cap.sla_minutes if hitl else None
        return OrchestratorResult(
            capability_id=cap.capability_id, capability_version=cap.version,
            result=output.result, confidence=confidence, threshold=cap.confidence_threshold,
            pathway=pathway, engine_selected=engine_used, engines_tried=tried,
            engines_skipped=skipped, explanation=output.explanation,
            requires_hitl=hitl, hitl_reason=hitl_reason, hitl_sla_minutes=sla,
            hitl_due_at=(datetime.utcnow() + timedelta(minutes=sla)) if sla else None,
            latency_ms=latency_ms, cost=spent, correlation_id=correlation_id,
            input_hash=input_hash, supporting=output.supporting,
        )

    def _audit(self, result: OrchestratorResult, sink=None) -> None:
        sink = sink or self.audit_sink
        if sink is None:
            return
        try:
            sink(result)
        except Exception:                                # noqa: BLE001
            # An audit failure must never fail the request it describes, but it
            # must be loud — an unaudited AI decision is a compliance gap.
            logger.exception("orchestrator audit write failed for %s", result.capability_id)

    # ── Introspection for GET /ai/capabilities ───────────────────────────────
    def describe(self) -> List[Dict[str, Any]]:
        out = []
        for cap in self.capabilities.values():
            chain = self._chain(cap)
            resolves_at = next(
                (e for e in chain if self._skip_reason(cap, e, 0.0) is None), None)
            engine = self.engines.get(resolves_at) if resolves_at else None
            out.append({
                "capability_id": cap.capability_id,
                "capability_name": cap.capability_name,
                "version": cap.version,
                "description": cap.description,
                "preferred_engine": cap.preferred_engine,
                "fallback_chain": chain,
                "confidence_threshold": cap.confidence_threshold,
                "latency_target_ms": cap.latency_target_ms,
                "cost_limit_per_call": cap.cost_limit_per_call,
                "business_criticality": cap.business_criticality,
                "requires_hitl": cap.requires_hitl,
                "conditional_hitl": cap.hitl_when is not None,
                "hitl_sla_minutes": cap.sla_minutes,
                "cache_ttl_seconds": cap.cache_ttl_seconds,
                "resolves_at_engine": resolves_at,
                "resolves_at_tier": engine.tier if engine else None,
                # Tier 6 only. Tier 7 is a person, not a model — counting human
                # review as an LLM call would understate the token-efficiency
                # figure this whole architecture exists to protect.
                "invokes_llm": bool(engine and engine.tier == 6),
                # False means no adapter is wired at the preferred tier, so the
                # capability is declared but degrades down the chain. Surfaced
                # rather than hidden — a capability that silently lands on human
                # review looks identical to one that is working.
                "adapter_available": engine_adapters.handler_for(
                    cap.capability_id, cap.preferred_engine) is not None,
            })
        return out

    def engine_status(self) -> List[Dict[str, Any]]:
        return [
            {
                "engine_id": e.engine_id, "tier": e.tier, "name": e.name,
                "health": e.health, "circuit": self.breaker.state(e.engine_id),
                "cost_per_call": e.cost_per_call,
                "typical_latency_ms": e.typical_latency_ms,
            }
            for e in sorted(self.engines.values(), key=lambda x: x.tier)
        ]


# Process-wide instance. The registries are configuration, not per-request state.
_orchestrator: Optional[Orchestrator] = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator
