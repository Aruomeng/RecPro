"""G4 composition boundary for the deterministic in-process Agent slice."""

from __future__ import annotations

from typing import Any

from backend.app.recommendation.agents.orchestrator import (
    OrchestrationDeadlineExceeded,
    OrchestrationRequest,
    OrchestrationResult,
    RecommendationOrchestrator,
)
from backend.app.recommendation.agents.registry import AgentRegistry
from backend.app.recommendation.agents.rule_agents import DEFAULT_RULE_AGENTS
from backend.app.recommendation.ports.agent_logging import AgentExecutionLogPort


def build_rule_orchestrator() -> RecommendationOrchestrator:
    """Build the G4 rule registry without exposing Agent implementations to HTTP."""

    return RecommendationOrchestrator(
        AgentRegistry({agent.name: agent for agent in DEFAULT_RULE_AGENTS})
    )


async def persist_orchestration(
    connection: Any,
    result: OrchestrationResult,
    *,
    log_port: AgentExecutionLogPort,
) -> None:
    """Append one orchestration and all dispatch facts in one caller transaction.

    This function deliberately never commits or rolls back.  The application
    service that owns the recommendation result must decide whether the whole
    batch is committed or rolled back together.
    """

    for dispatch in result.dispatches:
        await log_port.append_message(connection, dispatch.message)
        await log_port.append_result(
            connection,
            task_id=result.task_id,
            trace_id=result.trace_id,
            context_version=result.context_version,
            message=dispatch.message,
            result=dispatch.result,
        )
    await log_port.append_orchestration_result(
        connection,
        task_id=result.task_id,
        trace_id=result.trace_id,
        context_version=result.context_version,
        schema_version="g4-orchestrator-v1",
        status=result.status.value,
        replan_count=result.replan_count,
        payload=result.payload,
        transitions=result.transitions,
        trace=result.trace,
    )


__all__ = [
    "OrchestrationDeadlineExceeded",
    "OrchestrationRequest",
    "OrchestrationResult",
    "RecommendationOrchestrator",
    "build_rule_orchestrator",
    "persist_orchestration",
]
