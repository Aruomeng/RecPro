"""G4 Agent contracts and in-process orchestration boundary."""

from backend.app.recommendation.agents.base import Agent
from backend.app.recommendation.agents.orchestrator import (
    OrchestrationRequest,
    OrchestrationResult,
    RecommendationOrchestrator,
)
from backend.app.recommendation.agents.registry import AgentRegistry

__all__ = [
    "Agent",
    "AgentRegistry",
    "OrchestrationRequest",
    "OrchestrationResult",
    "RecommendationOrchestrator",
]
