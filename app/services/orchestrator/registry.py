"""Capability Registry and Engine Registry.

Source: EHSERA AI Platform Enterprise Architecture ISMS v1.0, Sections 1.3
(Engine Registry) and 2 (Capability Registry).

The registry is the mechanism that enforces the LEAN Engine Hierarchy. A
capability is a named contract — "classify incident severity" — that declares
which engine should serve it, what to fall back to, what confidence is required,
and what it may cost. Workflow code asks for the capability; it never picks an
engine. That decoupling is the whole point:

  · an engine can be swapped without touching workflow code
  · thresholds are owned by the safety team, not by whoever wrote the endpoint
  · every AI cost is attributable without instrumenting any workflow

Section 2.3 also lists A/B traffic splitting as a registry feature. Not
implemented — noted here so its absence is a known gap rather than an oversight.
"""
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


# ══════════════════════════════════════════════════════════════════════════════
# Engine Registry (Section 1.3)
#
#   L1 Workflow  L2 Rules  L3 Knowledge Graph  L4 Vector
#   L5 ML        L6 LLM    L7 Human Review
# ══════════════════════════════════════════════════════════════════════════════

TIER_WORKFLOW = 1
TIER_RULES = 2
TIER_KG = 3
TIER_VECTOR = 4
TIER_ML = 5
TIER_LLM = 6
TIER_HUMAN = 7

HEALTH_OK = "OK"
HEALTH_DEGRADED = "DEGRADED"
HEALTH_OFFLINE = "OFFLINE"


@dataclass
class Engine:
    engine_id: str
    tier: int
    name: str
    cost_per_call: float
    typical_latency_ms: int
    health: str = HEALTH_OK
    # Set for engines the platform does not have yet. They stay in the registry
    # so the fallback chains read as the spec defines them and so
    # GET /ai/capabilities reports honestly what is and is not available.
    handler: Optional[Callable] = None

    @property
    def available(self) -> bool:
        return self.health == HEALTH_OK and self.handler is not None


# Engine IDs match the spec's Section 1.3 table so the two can be diffed.
WF_ENGINE = "WF-ENGINE-01"
RULES_ENGINE = "RE-ENGINE-01"
KG_ENGINE = "KG-ENGINE-01"
VECTOR_ENGINE = "VS-ENGINE-01"
ML_ENGINE = "ML-ENGINE-01"
LLM_ENGINE = "LLM-ENGINE-01"
LLM_FALLBACK = "LLM-ENGINE-02"
HUMAN_ENGINE = "HR-ENGINE-01"


def default_engines() -> Dict[str, Engine]:
    """The engine roster. Handlers are attached by app.services.orchestrator.engines.

    L3/L4/L5 are registered OFFLINE on purpose: the platform has no Knowledge
    Graph, vector store or ML service yet. Registering them lets the fallback
    chains stay faithful to the spec while the Orchestrator honestly skips them,
    rather than pretending a capability is served at a tier it is not.
    """
    return {
        WF_ENGINE:    Engine(WF_ENGINE, TIER_WORKFLOW, "Workflow Engine", 0.0, 50),
        RULES_ENGINE: Engine(RULES_ENGINE, TIER_RULES, "Rules Engine", 0.0, 100),
        KG_ENGINE:    Engine(KG_ENGINE, TIER_KG, "Knowledge Graph (Neo4j)", 0.001, 200,
                             health=HEALTH_OFFLINE),
        VECTOR_ENGINE: Engine(VECTOR_ENGINE, TIER_VECTOR, "Vector Search (pgvector)", 0.001, 300,
                              health=HEALTH_OFFLINE),
        ML_ENGINE:    Engine(ML_ENGINE, TIER_ML, "ML Classification", 0.005, 500,
                             health=HEALTH_OFFLINE),
        LLM_ENGINE:   Engine(LLM_ENGINE, TIER_LLM, "LLM (primary)", 0.03, 4000),
        LLM_FALLBACK: Engine(LLM_FALLBACK, TIER_LLM, "LLM (failover)", 0.03, 5000,
                             health=HEALTH_OFFLINE),
        HUMAN_ENGINE: Engine(HUMAN_ENGINE, TIER_HUMAN, "Human Review Queue", 0.0, 900_000),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Capability Registry (Section 2)
# ══════════════════════════════════════════════════════════════════════════════

CRITICAL = "CRITICAL"
HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"

# Section 3.5 — Human Review SLA by business criticality, in minutes.
HITL_SLA_MINUTES = {CRITICAL: 15, HIGH: 120, MEDIUM: 240, LOW: 1440}


@dataclass
class Capability:
    capability_id: str
    capability_name: str
    version: str
    preferred_engine: str
    fallback_chain: List[str]
    confidence_threshold: float
    latency_target_ms: int
    cost_limit_per_call: float
    business_criticality: str
    requires_hitl: bool = False
    cache_ttl_seconds: int = 0
    audit_level: str = "STANDARD"
    description: str = ""
    # Returns True when this specific result needs human sign-off even though
    # requires_hitl is False — e.g. P1/P2 incidents, critical-band risk scores.
    hitl_when: Optional[Callable] = None

    @property
    def sla_minutes(self) -> int:
        return HITL_SLA_MINUTES.get(self.business_criticality, 240)


# ── The registered capabilities ──────────────────────────────────────────────
# Those marked (spec) are transcribed from Section 2.2. The rest cover
# deterministic capabilities this platform already implements, registered so
# they resolve at L2 and count toward the >90% non-LLM target.

def default_capabilities() -> Dict[str, Capability]:
    caps = [
        Capability(
            "CAP-INC-001", "Incident Severity Classification", "1.0.0",
            preferred_engine=RULES_ENGINE,
            fallback_chain=[ML_ENGINE, LLM_ENGINE, HUMAN_ENGINE],
            confidence_threshold=0.90, latency_target_ms=500, cost_limit_per_call=0.01,
            business_criticality=CRITICAL,
            description="P1-P5 severity via the WF-03 decision tree, with HIPO and recurrence.",
            # Spec: "requires_hitl FALSE for P3-P5, TRUE for P1-P2 (mandatory
            # regulatory review regardless of engine confidence)."
            hitl_when=lambda r: (r or {}).get("priority") in ("P1", "P2"),
        ),
        Capability(
            "CAP-RISK-001", "Risk Assessment — L x S with Uplift", "1.0.0",
            preferred_engine=RULES_ENGINE,
            fallback_chain=[HUMAN_ENGINE],   # spec: no probabilistic fallback for risk scoring
            confidence_threshold=1.0, latency_target_ms=200, cost_limit_per_call=0.0,
            business_criticality=CRITICAL,
            description="WF-01 L x S, four mandatory uplifts, band and approval route.",
            # Spec: HITL for Final Risk Score >= 17 (Critical band).
            hitl_when=lambda r: (r or {}).get("adjusted_score") is not None
                                and r["adjusted_score"] >= 17,
        ),
        Capability(
            "CAP-PTW-001", "Permit-to-Work Gate Validation", "1.0.0",
            preferred_engine=RULES_ENGINE,
            fallback_chain=[HUMAN_ENGINE],
            confidence_threshold=1.0, latency_target_ms=300, cost_limit_per_call=0.0,
            business_criticality=CRITICAL, requires_hitl=True,
            description=(
                "Six deterministic permit gates. Issuer and Receiver sign regardless. "
                "NOTE: served by app.services.gate_engine, which needs a DB session and a "
                "permit row, so it is not reachable through the stateless invoke() path. "
                "Registered here for the catalogue and the audit trail; "
                "GET /ai/capabilities reports adapter_available=false for it."
            ),
        ),
        Capability(
            "CAP-STAT-001", "Statutory Reportability", "1.0.0",
            preferred_engine=RULES_ENGINE,
            fallback_chain=[HUMAN_ENGINE],
            confidence_threshold=1.0, latency_target_ms=300, cost_limit_per_call=0.0,
            business_criticality=CRITICAL, requires_hitl=True,
            description="Appendix A reportability, regulator and deadline. Always human-authorised.",
        ),
        Capability(
            "CAP-CAPA-001", "CAPA Prioritisation", "1.0.0",
            preferred_engine=RULES_ENGINE,
            fallback_chain=[HUMAN_ENGINE],
            confidence_threshold=1.0, latency_target_ms=200, cost_limit_per_call=0.0,
            business_criticality=MEDIUM,
            description="WF-04 priority matrix and type-based due date.",
        ),
        Capability(
            "CAP-FAT-001", "Fatigue Index", "1.0.0",
            preferred_engine=RULES_ENGINE,
            fallback_chain=[HUMAN_ENGINE],
            confidence_threshold=1.0, latency_target_ms=200, cost_limit_per_call=0.0,
            business_criticality=HIGH,
            description="WF-07 fatigue index and band. Feeds permit gate 3.",
            hitl_when=lambda r: (r or {}).get("band") in ("signoff", "block"),
        ),
        Capability(
            "CAP-RAMS-001", "RAMS Document Quality Assessment", "1.0.0",
            preferred_engine=RULES_ENGINE,
            fallback_chain=[VECTOR_ENGINE, LLM_ENGINE, HUMAN_ENGINE],
            confidence_threshold=0.85, latency_target_ms=2000, cost_limit_per_call=0.05,
            business_criticality=HIGH,
            description="Six-criterion rubric. Structured fields deterministic, narrative via ML/LLM.",
            hitl_when=lambda r: (r or {}).get("score") is not None and r["score"] < 60,
        ),
        Capability(
            "CAP-DOC-001", "Safety Document Summarisation", "1.0.0",
            preferred_engine=LLM_ENGINE,
            fallback_chain=[LLM_FALLBACK, HUMAN_ENGINE],
            confidence_threshold=0.75, latency_target_ms=8000, cost_limit_per_call=0.10,
            business_criticality=MEDIUM, cache_ttl_seconds=86400,
            description="Genuine generation task. LLM is the correct tier, not a fallback.",
        ),
        Capability(
            "CAP-RCA-001", "Root Cause Analysis Support", "1.0.0",
            preferred_engine=RULES_ENGINE,
            fallback_chain=[VECTOR_ENGINE, LLM_ENGINE, HUMAN_ENGINE],
            confidence_threshold=0.80, latency_target_ms=10000, cost_limit_per_call=0.15,
            business_criticality=HIGH, requires_hitl=True,
            description="Investigation findings must be reviewed by a qualified investigator.",
        ),
        Capability(
            "CAP-CHAT-001", "AI Chat Assistant", "1.0.0",
            preferred_engine=LLM_ENGINE,
            fallback_chain=[LLM_FALLBACK, HUMAN_ENGINE],
            confidence_threshold=0.85, latency_target_ms=8000, cost_limit_per_call=0.10,
            business_criticality=MEDIUM, cache_ttl_seconds=0,
            description="Role-scoped conversational AI assistant with live HSE data briefings.",
        ),
    ]
    return {c.capability_id: c for c in caps}
