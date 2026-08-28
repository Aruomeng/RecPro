"""Deterministic ambient handlers; none of them call an LLM or write data."""

from __future__ import annotations

from time import perf_counter
from typing import Mapping

from backend.app.agent_workspace.ports.handlers import (
    WorkspaceAgentResult,
    WorkspaceDirectiveProposal,
    WorkspaceHandlerContext,
    WorkspaceObservation,
    WorkspaceProfileReadPort,
    WorkspaceReadToolPort,
)
from backend.app.agent_workspace.topic_graph import SessionTopicGraph


class ExplorationWorkspaceReadTools:
    """Adapt the existing bounded Exploration service to Workspace reads."""

    def __init__(self, exploration_service: object) -> None:
        self._service = exploration_service

    async def resource(self, resource_id: int) -> Mapping[str, object]:
        return await self._service.resource(resource_id)

    async def graph_neighbors(self, entity_id: str, *, limit: int) -> Mapping[str, object]:
        return await self._service.graph_neighbors(entity_id, limit=min(limit, 40))


class IntentWorkspaceHandler:
    agent_name = "IntentUnderstandingAgent"
    observation_types = frozenset({"QUERY_SUBMITTED"})

    async def handle(
        self, observation: WorkspaceObservation, context: WorkspaceHandlerContext,
    ) -> WorkspaceAgentResult:
        query = str(observation.payload.get("query", "")).strip()
        topics = SessionTopicGraph.extract_topics(query, observation.payload)
        reason = "QUERY_CONTEXT_NORMALIZED" if query else "EMPTY_QUERY_CONTEXT"
        return WorkspaceAgentResult(
            agent_name=self.agent_name,
            action="RETURN_RESULT",
            target="RecommendationOrchestrator",
            reason_code=reason,
            confidence=0.90 if topics else 0.70,
            evidence_refs=("session:query",),
            tool_calls=({"tool": "rule_classifier", "status": "UP", "topic_count": len(topics)},),
            outcome="SUCCESS" if query else "DEGRADED",
        )


class ResourceSemanticWorkspaceHandler:
    agent_name = "ResourceSemanticAgent"
    observation_types = frozenset({"GRAPH_NODE_SELECTED", "RESOURCE_OPENED"})

    def __init__(self, read_tools: WorkspaceReadToolPort | None = None) -> None:
        self._read_tools = read_tools

    async def handle(
        self, observation: WorkspaceObservation, context: WorkspaceHandlerContext,
    ) -> WorkspaceAgentResult:
        if self._read_tools is None:
            return WorkspaceAgentResult(
                agent_name=self.agent_name,
                action="FALLBACK",
                target="RecommendationPolicyAgent",
                reason_code="READ_TOOL_NOT_CONFIGURED",
                confidence=0.65,
                evidence_refs=("workspace:public-observation",),
                tool_calls=({"tool": "public_observation", "status": "DEGRADED"},),
                outcome="DEGRADED",
            )
        started = perf_counter()
        try:
            if observation.event_type == "GRAPH_NODE_SELECTED":
                entity_id = str(observation.payload.get("entity_id", ""))[:160]
                if not entity_id:
                    raise ValueError("entity id is required")
                result = await self._read_tools.graph_neighbors(entity_id, limit=40)
                count = len(result.get("nodes", [])) if isinstance(result, Mapping) else 0
                tool = "neo4j_public_neighbors"
                evidence = (f"neo4j:{entity_id}",)
            else:
                resource_id = int(observation.payload.get("resource_id", 0))
                if resource_id < 1:
                    raise ValueError("resource id is required")
                result = await self._read_tools.resource(resource_id)
                count = 1 if result else 0
                tool = "mysql_resource_detail"
                evidence = (f"resource:{resource_id}",)
        except Exception as exc:
            return WorkspaceAgentResult(
                agent_name=self.agent_name,
                action="DEGRADE",
                target="RecommendationPolicyAgent",
                reason_code="SEMANTIC_READ_UNAVAILABLE",
                confidence=0.60,
                evidence_refs=("workspace:public-observation",),
                tool_calls=({"tool": "bounded_read", "status": "DEGRADED", "error_type": type(exc).__name__},),
                outcome="DEGRADED",
            )
        return WorkspaceAgentResult(
            agent_name=self.agent_name,
            action="PROBE_RESOURCES",
            target="RecommendationPolicyAgent",
            reason_code="SEMANTIC_CONTEXT_VERIFIED",
            confidence=0.88 if count else 0.72,
            evidence_refs=evidence,
            tool_calls=({
                "tool": tool,
                "status": "UP",
                "result_count": min(count, 60),
                "duration_ms": max(0, int((perf_counter() - started) * 1000)),
                "read_only": True,
            },),
            outcome="SUCCESS" if count else "DEGRADED",
        )


class UserProfileWorkspaceHandler:
    agent_name = "UserProfileAgent"
    observation_types = frozenset({"SESSION_STARTED"})

    def __init__(self, profile_reader: WorkspaceProfileReadPort | None = None) -> None:
        self._profile_reader = profile_reader

    async def handle(
        self, observation: WorkspaceObservation, context: WorkspaceHandlerContext,
    ) -> WorkspaceAgentResult:
        if not context.personalization_enabled:
            raise PermissionError("profile handler requires personalization consent")
        if self._profile_reader is None:
            return WorkspaceAgentResult(
                agent_name=self.agent_name,
                action="DEGRADE",
                target="RecommendationOrchestrator",
                reason_code="PROFILE_READER_NOT_CONFIGURED",
                confidence=0.60,
                evidence_refs=("consent:personalized-recommendation",),
                tool_calls=({"tool": "profile_snapshot_reader", "status": "DEGRADED"},),
                outcome="DEGRADED",
            )
        try:
            summary = await self._profile_reader.summary(observation.user_id)
        except Exception as exc:
            return WorkspaceAgentResult(
                agent_name=self.agent_name,
                action="DEGRADE",
                target="RecommendationOrchestrator",
                reason_code="PROFILE_READ_UNAVAILABLE",
                confidence=0.60,
                evidence_refs=("consent:personalized-recommendation",),
                tool_calls=({"tool": "profile_snapshot_reader", "status": "DEGRADED", "error_type": type(exc).__name__},),
                outcome="DEGRADED",
            )
        version = str(summary.get("profile_version", "current"))[:80]
        return WorkspaceAgentResult(
            agent_name=self.agent_name,
            action="READ_PROFILE",
            target="RecommendationOrchestrator",
            reason_code="CONSENTED_PROFILE_CONTEXT_READY",
            confidence=float(summary.get("confidence", 0.75)),
            evidence_refs=(f"profile:{version}", "consent:personalized-recommendation"),
            tool_calls=({"tool": "profile_snapshot_reader", "status": "UP", "read_only": True},),
        )


class RecommendationPolicyWorkspaceHandler:
    agent_name = "RecommendationPolicyAgent"
    observation_types = frozenset(
        {"SESSION_STARTED", "ROUTE_CHANGED", "GRAPH_NODE_SELECTED", "RESOURCE_OPENED",
         "READINESS_CHANGED", "EXTERNAL_CONTEXT_UPDATED", "RECOMMENDATION_COMPLETED",
         "FEEDBACK_RECORDED"}
    )
    _fallback_topics = ("多智能体", "推荐系统", "知识图谱", "智慧图书馆")

    async def handle(
        self, observation: WorkspaceObservation, context: WorkspaceHandlerContext,
    ) -> WorkspaceAgentResult:
        event_type = observation.event_type
        directives: list[WorkspaceDirectiveProposal] = []
        evidence = ["workspace:context"]
        if event_type in {"SESSION_STARTED", "ROUTE_CHANGED", "EXTERNAL_CONTEXT_UPDATED"}:
            topics = list(context.top_topics)
            for source in context.external_context:
                values = source.get("values", {})
                if not isinstance(values, Mapping):
                    continue
                suggested = values.get("suggested_topics", [])
                if isinstance(suggested, list):
                    topics.extend(str(item) for item in suggested[:8])
                if isinstance(values.get("topic"), str):
                    topics.append(str(values["topic"]))
                source_id = str(source.get("source_id", "external"))
                evidence.append(f"external:{source_id}")
            topics = list(dict.fromkeys(item[:80] for item in topics if item.strip()))[:8]
            if not topics:
                topics = list(self._fallback_topics)
                evidence.append("fallback:policy-topics")
            directives.append(WorkspaceDirectiveProposal(
                "SUGGEST_TOPICS", "home", "SUGGESTION", {"topics": topics},
                "CONTEXT_TOPICS_AVAILABLE", 0.86, tuple(evidence), True,
            ))
            density = "DETAILED" if observation.mode == "guest" else "BALANCED"
            directives.append(WorkspaceDirectiveProposal(
                "SET_EXPLANATION_DENSITY", "global", "AUTO_APPLY", {"density": density},
                "IDENTITY_MODE_ADAPTATION", 0.84, ("session:mode",), True,
            ))
        if event_type == "ROUTE_CHANGED":
            output_type = "READING_PATH" if context.route == "/path" else "TOPIC_RESOURCES"
            directives.append(WorkspaceDirectiveProposal(
                "PREFER_OUTPUT_TYPE", context.route, "SUGGESTION", {"output_type": output_type},
                "ROUTE_INTENT_HINT", 0.78, ("session:route",), True,
            ))
        elif event_type in {"GRAPH_NODE_SELECTED", "RESOURCE_OPENED"}:
            label = str(observation.payload.get("label") or observation.payload.get("title") or "当前知识实体")[:80]
            directives.append(WorkspaceDirectiveProposal(
                "SUGGEST_NEXT_ACTION", context.route, "SUGGESTION",
                {"label": f"围绕“{label}”生成关联书单", "action": "OPEN_RECOMMEND", "query": label},
                "SEMANTIC_CONTEXT_AVAILABLE", 0.84, ("workspace:selected-entity",), True,
            ))
        elif event_type == "READINESS_CHANGED":
            degraded = [name for name, status in context.source_statuses.items() if status == "DEGRADED"]
            if degraded:
                directives.append(WorkspaceDirectiveProposal(
                    "SHOW_DEGRADED_NOTICE", "global", "NOTICE",
                    {"components": degraded, "message": "部分检索通道暂不可用，系统将保留可用通道继续工作。"},
                    "RUNTIME_CHANNEL_DEGRADED", 1.0,
                    tuple(f"readiness:{item}" for item in degraded), False,
                ))
        elif event_type == "RECOMMENDATION_COMPLETED":
            directives.append(WorkspaceDirectiveProposal(
                "SUGGEST_NEXT_ACTION", "recommend", "SUGGESTION",
                {"label": "在知识图谱中查看结果关联", "action": "OPEN_GRAPH", "query": context.query},
                "RECOMMENDATION_CONTEXT_READY", 0.81,
                ("workspace:recommendation-result",), True,
            ))
        elif event_type == "FEEDBACK_RECORDED":
            directives.append(WorkspaceDirectiveProposal(
                "SUGGEST_NEXT_ACTION", "global", "SUGGESTION",
                {"label": "依据刚才的反馈重新推荐", "action": "RECOMMEND_AGAIN"},
                "FEEDBACK_POLICY_REFRESH", 0.88, ("workspace:feedback",), True,
            ))
        return WorkspaceAgentResult(
            agent_name=self.agent_name,
            action="PLAN_RECALL",
            target="User",
            reason_code=f"{event_type}_POLICY_EVALUATED",
            confidence=0.84,
            evidence_refs=tuple(dict.fromkeys(evidence)),
            tool_calls=({"tool": "policy_engine", "status": "UP", "llm_requests": 0},),
            directives=tuple(directives),
        )


def default_workspace_handlers(
    *,
    read_tools: WorkspaceReadToolPort | None = None,
    profile_reader: WorkspaceProfileReadPort | None = None,
) -> tuple[object, ...]:
    return (
        IntentWorkspaceHandler(),
        UserProfileWorkspaceHandler(profile_reader),
        ResourceSemanticWorkspaceHandler(read_tools),
        RecommendationPolicyWorkspaceHandler(),
    )


__all__ = [
    "ExplorationWorkspaceReadTools",
    "IntentWorkspaceHandler",
    "RecommendationPolicyWorkspaceHandler",
    "ResourceSemanticWorkspaceHandler",
    "UserProfileWorkspaceHandler",
    "default_workspace_handlers",
]
