"""Deterministic in-process G4 Orchestrator with explicit dynamic branches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from backend.app.recommendation.agents.registry import AgentRegistry
from backend.app.shared_kernel.contracts.agent import AgentDispatch, AgentMessage, AgentResult
from backend.app.shared_kernel.contracts.enums import AgentActionType, MessageType, TaskStatus
from backend.app.shared_kernel.contracts.state import can_transition


@dataclass(frozen=True, slots=True)
class OrchestrationRequest:
    task_id: UUID
    trace_id: UUID
    user_id: int
    session_id: UUID
    input_text: str | None = None
    resource_types: tuple[str, ...] = ("BOOK", "PAPER")
    output_type: str | None = None
    limit: int = 5
    constraints: dict[str, Any] | None = None
    context_version: int = 1
    evaluation_at: datetime | None = None
    deadline_at: datetime | None = None
    scene: str = "HOME"
    initial_status: TaskStatus = TaskStatus.CREATED

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, UUID) or not isinstance(self.trace_id, UUID):
            raise ValueError("task_id and trace_id must be UUID values")
        if not isinstance(self.session_id, UUID):
            raise ValueError("session_id must be a UUID")
        if isinstance(self.user_id, bool) or self.user_id < 1:
            raise ValueError("user_id must be positive")
        if not isinstance(self.limit, int) or isinstance(self.limit, bool) or not 1 <= self.limit <= 20:
            raise ValueError("limit must be between 1 and 20")
        if not isinstance(self.resource_types, tuple):
            raise ValueError("resource_types must be a tuple")
        if self.context_version < 1:
            raise ValueError("context_version must be positive")
        if self.evaluation_at is not None and (
            self.evaluation_at.tzinfo is None or self.evaluation_at.utcoffset() is None
        ):
            raise ValueError("evaluation_at must be timezone-aware")
        if self.deadline_at is not None and (
            self.deadline_at.tzinfo is None or self.deadline_at.utcoffset() is None
        ):
            raise ValueError("deadline_at must be timezone-aware")
        if not isinstance(self.scene, str) or not self.scene.strip():
            raise ValueError("scene must be a non-blank string")
        if self.initial_status not in {
            TaskStatus.CREATED,
            TaskStatus.WAITING_CLARIFICATION,
        }:
            raise ValueError(
                "initial_status must be CREATED or WAITING_CLARIFICATION"
            )


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    task_id: UUID
    trace_id: UUID
    status: TaskStatus
    context_version: int
    replan_count: int
    payload: dict[str, object]
    transitions: tuple[dict[str, object], ...]
    trace: tuple[dict[str, object], ...]
    dispatches: tuple[AgentDispatch, ...] = ()


class OrchestrationDeadlineExceeded(TimeoutError):
    """The request deadline elapsed before a next Agent dispatch."""


class RecommendationOrchestrator:
    """Only this class may advance global status or choose the next Agent."""

    def __init__(self, registry: AgentRegistry, *, schema_version: str = "g4-orchestrator-v1") -> None:
        self._registry = registry
        self._schema_version = schema_version

    async def run(self, request: OrchestrationRequest) -> OrchestrationResult:
        now = datetime.now(UTC)
        deadline = request.deadline_at or now + timedelta(seconds=5)
        if deadline <= now:
            raise OrchestrationDeadlineExceeded("orchestration deadline has elapsed")
        constraints = dict(request.constraints or {})
        evaluation_at = request.evaluation_at or now
        trace: list[dict[str, object]] = []
        transitions: list[dict[str, object]] = []
        dispatches: list[AgentDispatch] = []
        results: dict[str, AgentResult[dict[str, object]]] = {}
        current = request.initial_status
        replan_count = 0

        def transition(target: TaskStatus, reason: str) -> None:
            nonlocal current
            if not can_transition(current, target):
                raise RuntimeError(f"illegal G4 state transition: {current.value}->{target.value}")
            transitions.append(
                {
                    "from_status": current.value,
                    "to_status": target.value,
                    "context_version": request.context_version,
                    "reason_code": reason,
                }
            )
            current = target

        async def dispatch(
            *,
            receiver: str,
            message_type: MessageType,
            payload: dict[str, object],
            attempt: int = 1,
        ) -> dict[str, object]:
            if datetime.now(UTC) >= deadline:
                raise OrchestrationDeadlineExceeded("orchestration deadline exceeded")
            key = f"{request.task_id}:{receiver}:{request.context_version}:{attempt}:{len(trace) + 1}"
            message = AgentMessage(
                schema_version=self._schema_version,
                message_id=uuid5(NAMESPACE_URL, f"message:{key}"),
                trace_id=request.trace_id,
                task_id=request.task_id,
                sender="RecommendationOrchestrator",
                receiver=receiver,
                message_type=message_type,
                payload=payload,
                deadline_at=deadline,
                attempt=attempt,
                idempotency_key=key,
                context_version=request.context_version,
                created_at=now,
            )
            result = await self._registry.dispatch(message)
            results[receiver] = result
            dispatches.append(AgentDispatch(message=message, result=result))
            step = len(trace) + 1
            trace.append(
                {
                    "step_no": step,
                    "agent_name": result.agent_name,
                    "agent_version": result.agent_version,
                    "message_type": message_type.value,
                    "status": result.status.value,
                    "confidence": result.confidence,
                    "fallback_used": result.fallback_used,
                    "duration_ms": result.duration_ms,
                    "warnings": list(result.warnings),
                    "error_code": result.error_code,
                    "autonomy": result.decision.as_dict() if result.decision else None,
                    "input_digest": f"message:{message.message_id}",
                }
            )
            if result.payload is None:
                raise RuntimeError(f"Agent {receiver} returned no payload")
            return result.payload

        transition(TaskStatus.UNDERSTANDING, "G4_RULE_UNDERSTANDING")
        intent = await dispatch(
            receiver="IntentUnderstandingAgent",
            message_type=MessageType.INTENT_RESOLVE,
            payload={
                "input_text": request.input_text,
                "resource_types": list(request.resource_types),
                "output_type": request.output_type,
                "scene": request.scene,
                "evaluation_at": evaluation_at.isoformat(),
            },
        )
        transition(TaskStatus.PROBING, "G4_RULE_PROBE")
        profile = await dispatch(
            receiver="UserProfileAgent",
            message_type=MessageType.PROFILE_BUILD,
            payload={
                "user_id": request.user_id,
                "constraints": constraints,
                "evaluation_at": evaluation_at.isoformat(),
            },
        )
        probe = await dispatch(
            receiver="ResourceSemanticAgent",
            message_type=MessageType.SEMANTIC_PROBE,
            payload={
                "intent": intent,
                "constraints": constraints,
                "evaluation_at": evaluation_at.isoformat(),
            },
        )
        transition(TaskStatus.DECIDING, "G4_RULE_POLICY")
        policy = await dispatch(
            receiver="RecommendationPolicyAgent",
            message_type=MessageType.POLICY_DECIDE,
            payload={
                "intent": intent,
                "profile": profile,
                "probe": probe,
                "constraints": constraints,
                "output_type": request.output_type,
                "evaluation_at": evaluation_at.isoformat(),
            },
        )
        warnings = self._collect_warnings(results)
        orchestration_warnings: list[str] = []
        policy_result = results["RecommendationPolicyAgent"]
        if policy_result.decision is None:
            raise RuntimeError("RecommendationPolicyAgent returned no autonomy decision")
        if policy_result.decision.action is AgentActionType.ASK_CLARIFICATION:
            if policy.get("delivery_strategy") != "GUIDED":
                raise RuntimeError("policy clarification action conflicts with delivery strategy")
            transition(TaskStatus.WAITING_CLARIFICATION, "MISSING_REQUIRED_SLOTS")
            payload = {
                "task_id": str(request.task_id),
                "trace_id": str(request.trace_id),
                "status": current.value,
                "context_version": request.context_version,
                "intent": intent,
                "decision": policy,
                "questions": list(policy.get("clarification_questions", [])),
                "warnings": warnings,
                "agent_results": self._public_results(results),
            }
            return OrchestrationResult(
                task_id=request.task_id,
                trace_id=request.trace_id,
                status=current,
                context_version=request.context_version,
                replan_count=replan_count,
                payload=payload,
                transitions=tuple(transitions),
                trace=tuple(trace),
                dispatches=tuple(dispatches),
            )
        if policy_result.decision.action not in {
            AgentActionType.PLAN_RECALL,
            AgentActionType.DEGRADE,
        }:
            raise RuntimeError(
                "RecommendationPolicyAgent proposed an action that cannot continue the task"
            )

        transition(TaskStatus.RECALLING, "G4_RULE_RECALL")
        recall = await dispatch(
            receiver="CandidateRecallAgent",
            message_type=MessageType.RECALL_EXECUTE,
            payload={
                "intent": intent,
                "profile": profile,
                "probe": probe,
                "constraints": constraints,
                "limit": request.limit,
                "query_text": request.input_text or " ".join(
                    str(term) for term in intent.get("topic_terms", [])
                ),
                "replan_count": replan_count,
                "evaluation_at": evaluation_at.isoformat(),
            },
        )
        transition(TaskStatus.RANKING, "G4_RULE_RANK")
        ranking = await dispatch(
            receiver="RankingAgent",
            message_type=MessageType.RANK_EXECUTE,
            payload={
                "candidates": recall.get("candidates", []),
                "constraints": constraints,
                "replan_count": replan_count,
            },
        )
        ranking_result = results["RankingAgent"]
        if ranking_result.decision is None:
            raise RuntimeError("RankingAgent returned no autonomy decision")
        if ranking_result.decision.action is AgentActionType.REQUEST_REPLAN and replan_count == 0:
            transition(TaskStatus.REPLANNING, "COVERAGE_BELOW_THRESHOLD")
            replan_count = 1
            policy = await dispatch(
                receiver="RecommendationPolicyAgent",
                message_type=MessageType.POLICY_REPLAN,
                payload={
                    "intent": intent,
                    "profile": profile,
                    "probe": probe,
                    "constraints": {**constraints, "force_replan": False},
                    "output_type": request.output_type,
                    "replan_count": replan_count,
                    "evaluation_at": evaluation_at.isoformat(),
                },
                attempt=2,
            )
            policy_result = results["RecommendationPolicyAgent"]
            if policy_result.decision is None:
                raise RuntimeError("RecommendationPolicyAgent returned no replan autonomy decision")
            if policy_result.decision.action not in {
                AgentActionType.PLAN_RECALL,
                AgentActionType.DEGRADE,
            }:
                raise RuntimeError(
                    "RecommendationPolicyAgent proposed an unsupported replan action"
                )
            transition(TaskStatus.RECALLING, "G4_REPLAN_RECALL")
            recall = await dispatch(
                receiver="CandidateRecallAgent",
                message_type=MessageType.RECALL_EXECUTE,
                payload={
                    "intent": intent,
                    "profile": profile,
                    "probe": probe,
                    "constraints": {**constraints, "force_replan": False},
                    "limit": request.limit,
                    "query_text": request.input_text or " ".join(
                        str(term) for term in intent.get("topic_terms", [])
                    ),
                    "replan_count": replan_count,
                    "evaluation_at": evaluation_at.isoformat(),
                },
                attempt=2,
            )
            transition(TaskStatus.RANKING, "G4_REPLAN_RANK")
            ranking = await dispatch(
                receiver="RankingAgent",
                message_type=MessageType.RANK_EXECUTE,
                payload={
                    "candidates": recall.get("candidates", []),
                    "constraints": {**constraints, "force_replan": False},
                    "replan_count": replan_count,
                },
                attempt=2,
            )
        elif ranking_result.decision.action is AgentActionType.REQUEST_REPLAN:
            orchestration_warnings.append("REPLAN_BUDGET_EXHAUSTED")
        elif ranking_result.decision.action not in {
            AgentActionType.RETURN_RESULT,
            AgentActionType.DEGRADE,
        }:
            raise RuntimeError("RankingAgent proposed an unsupported continuation action")
        if replan_count == 1:
            ranking_result = results["RankingAgent"]
            if ranking_result.decision is None:
                raise RuntimeError("RankingAgent returned no replan autonomy decision")
            if ranking_result.decision.action is AgentActionType.REQUEST_REPLAN:
                orchestration_warnings.append("REPLAN_BUDGET_EXHAUSTED")
            elif ranking_result.decision.action not in {
                AgentActionType.RETURN_RESULT,
                AgentActionType.DEGRADE,
            }:
                raise RuntimeError("RankingAgent proposed an unsupported replan continuation action")
        transition(TaskStatus.EXPLAINING, "G4_RULE_EXPLAIN")
        explanation = await dispatch(
            receiver="ExplanationAgent",
            message_type=MessageType.EXPLAIN_EXECUTE,
            payload={"ranked_items": ranking.get("ranked_items", []), "policy": policy},
        )
        warnings = self._collect_warnings(results)
        for warning in orchestration_warnings:
            if warning not in warnings:
                warnings.append(warning)
        degraded = policy.get("delivery_strategy") == "DEGRADED" or bool(warnings) or not ranking.get("ranked_items")
        transition(TaskStatus.PERSISTING, "G4_RESULT_READY")
        transition(
            TaskStatus.DEGRADED_COMPLETED if degraded else TaskStatus.COMPLETED,
            "G4_DEGRADED" if degraded else "G4_COMPLETED",
        )
        payload = {
            "task_id": str(request.task_id),
            "trace_id": str(request.trace_id),
            "status": current.value,
            "context_version": request.context_version,
            "replan_count": replan_count,
            "intent": intent,
            "decision": policy,
            "items": list(ranking.get("ranked_items", [])),
            "explanations": list(explanation.get("explanations", [])),
            "warnings": warnings,
            "agent_results": self._public_results(results),
        }
        return OrchestrationResult(
            task_id=request.task_id,
            trace_id=request.trace_id,
            status=current,
            context_version=request.context_version,
            replan_count=replan_count,
            payload=payload,
            transitions=tuple(transitions),
            trace=tuple(trace),
            dispatches=tuple(dispatches),
        )

    @staticmethod
    def _collect_warnings(results: dict[str, AgentResult[dict[str, object]]]) -> list[str]:
        values: list[str] = []
        for result in results.values():
            for warning in result.warnings:
                if warning not in values:
                    values.append(warning)
        return values

    @staticmethod
    def _public_results(results: dict[str, AgentResult[dict[str, object]]]) -> dict[str, object]:
        return {
            name: {
                "status": result.status.value,
                "confidence": result.confidence,
                "warnings": list(result.warnings),
                "fallback_used": result.fallback_used,
                "evidence_refs": list(result.evidence_refs),
                "role": result.agent_name,
                "autonomy": result.decision.as_dict() if result.decision else None,
            }
            for name, result in results.items()
        }


__all__ = [
    "OrchestrationDeadlineExceeded",
    "OrchestrationRequest",
    "OrchestrationResult",
    "RecommendationOrchestrator",
]
