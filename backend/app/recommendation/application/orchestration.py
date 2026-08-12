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
from backend.app.recommendation.agents.real_agents import (
    CatalogCandidateRecallAgent,
    CatalogResourceSemanticAgent,
    MySQLProfileAgent,
)
from backend.app.recommendation.agents.base import RetryPolicy
from backend.app.recommendation.agents.llm_agents import (
    LLMExplanationAgent,
    LLMIntentUnderstandingAgent,
)
from backend.app.recommendation.agents.rule_agents import DEFAULT_RULE_AGENTS
from backend.app.catalog.ports.public import (
    CatalogRepository,
    GraphRecallPort,
    QueryEmbeddingPort,
    VectorRecallPort,
)
from backend.app.profile.ports.public import ProfileSnapshotReader
from backend.app.recommendation.ports.agent_logging import AgentExecutionLogPort
from backend.app.llm.ports.public import TextCapabilityProvider


def build_rule_orchestrator(
    *, llm_provider: TextCapabilityProvider | None = None
) -> RecommendationOrchestrator:
    """Build the G4 rule registry without exposing Agent implementations to HTTP."""

    agents = {agent.name: agent for agent in DEFAULT_RULE_AGENTS}
    if llm_provider is not None:
        agents["IntentUnderstandingAgent"] = LLMIntentUnderstandingAgent(llm_provider)
        agents["ExplanationAgent"] = LLMExplanationAgent(llm_provider)
    return RecommendationOrchestrator(AgentRegistry(agents))


def build_port_orchestrator(
    catalog: CatalogRepository,
    profile: ProfileSnapshotReader,
    *,
    graph: GraphRecallPort | None = None,
    graph_version: str | None = None,
    vector: VectorRecallPort | None = None,
    query_embedder: QueryEmbeddingPort | None = None,
    embedding_version: str | None = None,
    index_version: str | None = None,
    retry_policy: RetryPolicy = RetryPolicy(),
    llm_provider: TextCapabilityProvider | None = None,
    llm_intent_provider: TextCapabilityProvider | None = None,
    llm_explanation_provider: TextCapabilityProvider | None = None,
) -> RecommendationOrchestrator:
    """Compose read-only Catalog/Profile Agents without exposing adapters to HTTP.

    ``llm_provider`` remains the compatibility switch for enabling both LLM
    Agents.  The capability-specific arguments allow a reviewed runtime
    probe to exercise one external capability (for example Intent) while the
    evidence-constrained explanation path remains the deterministic rule
    implementation.  This keeps external-call scope explicit instead of
    silently multiplying requests over every ranked item.
    """

    agents = {
        agent.name: agent
        for agent in DEFAULT_RULE_AGENTS
        if agent.name not in {"UserProfileAgent", "ResourceSemanticAgent", "CandidateRecallAgent"}
    }
    agents.update(
        {
            "UserProfileAgent": MySQLProfileAgent(profile, retry_policy=retry_policy),
            "ResourceSemanticAgent": CatalogResourceSemanticAgent(
                catalog,
                graph=graph,
                vector=vector,
                retry_policy=retry_policy,
            ),
            "CandidateRecallAgent": CatalogCandidateRecallAgent(
                catalog,
                graph=graph,
                graph_version=graph_version,
                vector=vector,
                query_embedder=query_embedder,
                embedding_version=embedding_version,
                index_version=index_version,
                retry_policy=retry_policy,
            ),
        }
    )
    if llm_provider is not None:
        llm_intent_provider = llm_intent_provider or llm_provider
        llm_explanation_provider = llm_explanation_provider or llm_provider
    if llm_intent_provider is not None:
        agents["IntentUnderstandingAgent"] = LLMIntentUnderstandingAgent(llm_intent_provider)
    if llm_explanation_provider is not None:
        agents["ExplanationAgent"] = LLMExplanationAgent(llm_explanation_provider)
    return RecommendationOrchestrator(AgentRegistry(agents))


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
    "build_port_orchestrator",
    "persist_orchestration",
]
