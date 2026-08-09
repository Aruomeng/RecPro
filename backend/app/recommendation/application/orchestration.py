"""G4 composition boundary for the deterministic in-process Agent slice."""

from __future__ import annotations

from backend.app.recommendation.agents.orchestrator import (
    OrchestrationDeadlineExceeded,
    OrchestrationRequest,
    OrchestrationResult,
    RecommendationOrchestrator,
)
from backend.app.recommendation.agents.registry import AgentRegistry
from backend.app.recommendation.agents.rule_agents import DEFAULT_RULE_AGENTS


def build_rule_orchestrator() -> RecommendationOrchestrator:
    """Build the G4 rule registry without exposing Agent implementations to HTTP."""

    return RecommendationOrchestrator(
        AgentRegistry({agent.name: agent for agent in DEFAULT_RULE_AGENTS})
    )


__all__ = [
    "OrchestrationDeadlineExceeded",
    "OrchestrationRequest",
    "OrchestrationResult",
    "RecommendationOrchestrator",
    "build_rule_orchestrator",
]
