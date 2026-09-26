"""AI Orchestration layer — LEAN engine hierarchy enforcement.

See core.Orchestrator. Entry point: get_orchestrator().invoke(capability_id, payload).
"""
from app.services.orchestrator.core import (  # noqa: F401
    AUTO_APPROVE, AUTO_REJECT, ESCALATE, HUMAN_REVIEW,
    Orchestrator, OrchestratorResult, UnknownCapability, get_orchestrator,
)
