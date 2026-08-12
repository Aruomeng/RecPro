"""Role profiles and action validation for autonomous G4 Agents.

The catalogue is intentionally local and immutable.  It gives every Agent a
research-visible role, goal, observation boundary, tool boundary, and finite
action set while keeping the Orchestrator as the only global state owner.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .agent import AgentDecision
from .enums import AgentActionType, AgentResultStatus


@dataclass(frozen=True, slots=True)
class AgentRoleProfile:
    name: str
    role: str
    goal: str
    observations: tuple[str, ...]
    tools: tuple[str, ...]
    allowed_actions: tuple[AgentActionType, ...]
    allowed_targets: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name, value in (
            ("name", self.name),
            ("role", self.role),
            ("goal", self.goal),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be non-blank")
        for field_name, values in (
            ("observations", self.observations),
            ("tools", self.tools),
            ("allowed_actions", self.allowed_actions),
            ("allowed_targets", self.allowed_targets),
        ):
            if not isinstance(values, tuple) or not values:
                raise ValueError(f"{field_name} must not be empty")
            if len(set(values)) != len(values):
                raise ValueError(f"{field_name} must not contain duplicates")


def _profile(
    name: str,
    role: str,
    goal: str,
    observations: tuple[str, ...],
    tools: tuple[str, ...],
    actions: tuple[AgentActionType, ...],
    targets: tuple[str, ...],
) -> AgentRoleProfile:
    return AgentRoleProfile(name, role, goal, observations, tools, actions, targets)


_COMMON = (AgentActionType.RETURN_RESULT, AgentActionType.FALLBACK, AgentActionType.DEGRADE)
_PROFILES: dict[str, AgentRoleProfile] = {
    "IntentUnderstandingAgent": _profile(
        "IntentUnderstandingAgent",
        "意图理解智能体",
        "将当前输入约束归一化为有限推荐意图，并报告是否需要补充信息。",
        ("input_text", "resource_types", "scene", "evaluation_at"),
        ("rule_classifier", "llm_provider"),
        _COMMON + (AgentActionType.ASK_CLARIFICATION,),
        ("RecommendationOrchestrator", "User"),
    ),
    "UserProfileAgent": _profile(
        "UserProfileAgent",
        "用户画像智能体",
        "读取指定时点的用户画像快照，并在证据不足时报告冷启动状态。",
        ("user_id", "constraints", "evaluation_at"),
        ("profile_snapshot_reader", "behavior_projection"),
        _COMMON + (AgentActionType.READ_PROFILE,),
        ("RecommendationOrchestrator",),
    ),
    "ResourceSemanticAgent": _profile(
        "ResourceSemanticAgent",
        "资源语义探测智能体",
        "评估当前资源索引和元数据是否足以支持后续召回。",
        ("intent", "constraints", "evaluation_at"),
        ("mysql_catalog", "graph_probe", "vector_probe"),
        _COMMON + (AgentActionType.PROBE_RESOURCES,),
        ("RecommendationOrchestrator", "RecommendationPolicyAgent"),
    ),
    "RecommendationPolicyAgent": _profile(
        "RecommendationPolicyAgent",
        "交互策略智能体",
        "基于意图、画像、探测和反馈状态选择下一步交互与召回计划。",
        ("intent", "profile", "probe", "constraints", "output_type"),
        ("policy_engine", "retrieval_plan_builder"),
        _COMMON + (AgentActionType.PLAN_RECALL, AgentActionType.ASK_CLARIFICATION),
        ("RecommendationOrchestrator", "CandidateRecallAgent", "User"),
    ),
    "CandidateRecallAgent": _profile(
        "CandidateRecallAgent",
        "候选召回智能体",
        "选择可用检索通道并返回带来源证据的候选集合。",
        ("intent", "profile", "probe", "constraints", "limit"),
        ("mysql_catalog", "neo4j_graph", "chroma_vector", "query_embedder"),
        _COMMON + (AgentActionType.SELECT_CHANNELS,),
        ("RecommendationOrchestrator", "RankingAgent"),
    ),
    "RankingAgent": _profile(
        "RankingAgent",
        "排序与重排智能体",
        "生成稳定、可解释的排序，并在质量门槛不足时提出一次重规划。",
        ("candidates", "constraints", "replan_count"),
        ("scoring_service", "diversity_service"),
        _COMMON + (AgentActionType.REQUEST_REPLAN,),
        ("RecommendationOrchestrator", "RecommendationPolicyAgent", "ExplanationAgent"),
    ),
    "ExplanationAgent": _profile(
        "ExplanationAgent",
        "证据解释智能体",
        "只基于已验证证据生成解释，证据不足时主动降级为模板。",
        ("ranked_items", "policy"),
        ("evidence_validator", "template_renderer", "llm_provider"),
        _COMMON + (AgentActionType.RENDER_EVIDENCE,),
        ("RecommendationOrchestrator", "User"),
    ),
    "FeedbackLearningAgent": _profile(
        "FeedbackLearningAgent",
        "反馈学习智能体",
        "将曝光和反馈事实转化为受约束的画像增量提案，不直接修改长期画像。",
        ("impression", "feedback", "behavior", "current_profile"),
        ("feedback_service", "outbox_repository"),
        _COMMON + (AgentActionType.PROPOSE_PROFILE_DELTA,),
        ("RecommendationOrchestrator", "UserProfileAgent"),
    ),
}

ROLE_PROFILES: Mapping[str, AgentRoleProfile] = MappingProxyType(_PROFILES)


class AgentAutonomyError(ValueError):
    """An Agent proposed an action outside its declared role boundary."""


def profile_for(agent_name: str) -> AgentRoleProfile:
    try:
        return ROLE_PROFILES[agent_name]
    except KeyError as exc:
        raise AgentAutonomyError(f"no role profile registered for {agent_name}") from exc


def validate_decision(agent_name: str, decision: AgentDecision) -> AgentDecision:
    profile = profile_for(agent_name)
    if decision.action not in profile.allowed_actions:
        raise AgentAutonomyError(
            f"{agent_name} cannot propose action {decision.action.value}"
        )
    if decision.target not in profile.allowed_targets:
        raise AgentAutonomyError(
            f"{agent_name} cannot target {decision.target}"
        )
    return decision


def decision_from_dict(value: object) -> AgentDecision:
    """Parse a persisted/public decision without accepting free-form actions."""

    if not isinstance(value, Mapping):
        raise AgentAutonomyError("autonomy decision must be a mapping")
    try:
        action = AgentActionType(value["action"])
        target = value["target"]
        reason_code = value["reason_code"]
        confidence = value["confidence"]
        parameters = value.get("parameters", {})
        evidence_refs = tuple(value.get("evidence_refs", ()))
        return AgentDecision(
            action=action,
            target=target,
            reason_code=reason_code,
            confidence=confidence,
            parameters=parameters,
            evidence_refs=evidence_refs,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AgentAutonomyError("autonomy decision is not a valid contract") from exc


def validate_decision_dict(agent_name: str, value: object) -> AgentDecision:
    """Parse and validate a decision emitted in a trace or HTTP projection."""

    return validate_decision(agent_name, decision_from_dict(value))


def default_decision(
    agent_name: str,
    *,
    status: AgentResultStatus,
    fallback_used: bool,
) -> AgentDecision:
    action = AgentActionType.FALLBACK if fallback_used or status is AgentResultStatus.PARTIAL else AgentActionType.RETURN_RESULT
    target = "RecommendationOrchestrator"
    return validate_decision(
        agent_name,
        AgentDecision(
            action=action,
            target=target,
            reason_code="LOCAL_FALLBACK" if action is AgentActionType.FALLBACK else "LOCAL_RESULT",
            confidence=0.5 if action is AgentActionType.FALLBACK else 0.8,
        ),
    )


def attach_decision(payload: dict[str, Any], decision: AgentDecision) -> dict[str, Any]:
    """Add a reserved, persisted view of the decision to an Agent payload."""

    if "_agent_decision" in payload:
        raise AgentAutonomyError("Agent payload cannot override _agent_decision")
    result = dict(payload)
    result["_agent_decision"] = decision.as_dict()
    return result


def assert_payload_decision(payload: object, decision: AgentDecision) -> None:
    if not isinstance(payload, dict) or payload.get("_agent_decision") != decision.as_dict():
        raise AgentAutonomyError("Agent payload decision does not match AgentResult.decision")


__all__ = [
    "AgentAutonomyError",
    "AgentRoleProfile",
    "ROLE_PROFILES",
    "assert_payload_decision",
    "attach_decision",
    "decision_from_dict",
    "default_decision",
    "profile_for",
    "validate_decision",
    "validate_decision_dict",
]
