"""Deterministic G4 Agent implementations used by the first orchestrator slice.

These Agents intentionally use only structured payloads.  They are replaceable
ports for later MySQL/vector/graph/LLM adapters and do not import one another.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid5

from backend.app.recommendation.agents.base import Agent
from backend.app.recommendation.agents.intent_guidance import looks_like_guided_clarification
from backend.app.recommendation.agents.topic_terms import extract_topic_terms
from backend.app.shared_kernel.contracts.autonomy import (
    attach_decision,
    default_decision,
    validate_decision,
)
from backend.app.shared_kernel.contracts.agent import AgentDecision
from backend.app.recommendation.domain.output_type_stability import (
    DEFAULT_HYSTERESIS_MARGIN,
    DEFAULT_MIN_OUTPUT_TYPE_ROUNDS,
    DEFAULT_TOPIC_FOCUS_INFER_THRESHOLD,
    infer_auto_output_type,
    stabilize_output_type,
)
from backend.app.shared_kernel.contracts.agent import AgentMessage, AgentResult
from backend.app.shared_kernel.contracts.enums import AgentActionType, AgentResultStatus


def _result(
    message: AgentMessage,
    *,
    agent_name: str,
    agent_version: str,
    payload: dict[str, object] | None,
    confidence: float,
    status: AgentResultStatus = AgentResultStatus.SUCCESS,
    warnings: tuple[str, ...] = (),
    fallback_used: bool = False,
    error_code: str | None = None,
    decision: AgentDecision | None = None,
) -> AgentResult[dict[str, object]]:
    resolved_decision = validate_decision(
        agent_name,
        decision
        or default_decision(
            agent_name,
            status=status,
            fallback_used=fallback_used,
        ),
    )
    return AgentResult(
        result_id=uuid5(message.message_id, f"result:{agent_name}:{message.attempt}"),
        input_message_id=message.message_id,
        agent_name=agent_name,
        agent_version=agent_version,
        status=status,
        confidence=max(0.0, min(1.0, confidence)),
        payload=attach_decision(dict(payload or {}), resolved_decision),
        evidence_refs=(f"rule:{agent_name}:{agent_version}",),
        warnings=warnings,
        fallback_used=fallback_used,
        tool_calls=(),
        error_code=error_code,
        duration_ms=0,
        decision=resolved_decision,
    )


class RuleIntentUnderstandingAgent:
    name = "IntentUnderstandingAgent"
    version = "intent-rule-v1"

    async def handle(self, message: AgentMessage) -> AgentResult[dict[str, object]]:
        text = str(message.payload.get("input_text") or "").strip()
        requested_types = [str(item) for item in message.payload.get("resource_types", [])]
        output_type = message.payload.get("output_type")
        if text and looks_like_guided_clarification(text):
            payload = {
                "intent_type": "UNCLEAR",
                "confidence": 0.72,
                "topic_terms": [],
                "resource_types": requested_types or ["BOOK", "PAPER"],
                "reason_codes": ["AMBIGUOUS_USER_GOAL"],
            }
            return _result(
                message,
                agent_name=self.name,
                agent_version="intent-guided-rule-v1",
                payload=payload,
                confidence=0.72,
                warnings=("LLM_INTENT_SKIPPED_AMBIGUOUS_INPUT",),
                fallback_used=True,
                decision=AgentDecision(
                    action=AgentActionType.ASK_CLARIFICATION,
                    target="RecommendationOrchestrator",
                    reason_code="AMBIGUOUS_USER_GOAL",
                    confidence=0.72,
                ),
            )
        if not text and not requested_types and output_type is None:
            payload = {
                "intent_type": "UNCLEAR",
                "confidence": 0.2,
                "topic_terms": [],
                "resource_types": [],
                "reason_codes": ["MISSING_REQUIRED_SLOTS"],
            }
            return _result(
                message,
                agent_name=self.name,
                agent_version=self.version,
                payload=payload,
                confidence=0.2,
                decision=AgentDecision(
                    action=AgentActionType.ASK_CLARIFICATION,
                    target="User",
                    reason_code="MISSING_REQUIRED_SLOTS",
                    confidence=0.2,
                ),
            )
        tokens = list(extract_topic_terms(text))
        return _result(
            message,
            agent_name=self.name,
            agent_version=self.version,
            payload={
                "intent_type": "TOPIC_RECOMMENDATION" if text else "GENERAL_RECOMMENDATION",
                "confidence": 0.86 if text else 0.58,
                "topic_terms": tokens,
                "resource_types": requested_types or ["BOOK", "PAPER"],
                "reason_codes": ["EXPLICIT_INPUT"] if text else ["DEFAULT_RESOURCE_TYPES"],
            },
            confidence=0.86 if text else 0.58,
            decision=AgentDecision(
                action=AgentActionType.RETURN_RESULT,
                target="RecommendationOrchestrator",
                reason_code="EXPLICIT_INPUT" if text else "DEFAULT_RESOURCE_TYPES",
                confidence=0.86 if text else 0.58,
            ),
        )


class RuleUserProfileAgent:
    name = "UserProfileAgent"
    version = "profile-rule-v1"

    async def handle(self, message: AgentMessage) -> AgentResult[dict[str, object]]:
        constraints = message.payload.get("constraints", {})
        empty = isinstance(constraints, dict) and bool(constraints.get("profile_empty"))
        confidence = 0.2 if empty else 0.72
        return _result(
            message,
            agent_name=self.name,
            agent_version=self.version,
            payload={
                "profile_version": "profile-g4-rule-v1",
                "confidence": confidence,
                "interest_strength": 0.0 if empty else 0.68,
                "topic_focus_strength": 0.0 if empty else 0.68,
                "signals": [] if empty else ["TOPIC_HISTORY"],
            },
            confidence=confidence,
            warnings=("SESSION_ONLY_PROFILE",) if empty else (),
            fallback_used=empty,
            decision=AgentDecision(
                action=AgentActionType.FALLBACK if empty else AgentActionType.READ_PROFILE,
                target="RecommendationOrchestrator",
                reason_code="PROFILE_EMPTY" if empty else "PROFILE_SNAPSHOT_READY",
                confidence=confidence,
            ),
        )


class RuleResourceSemanticAgent:
    name = "ResourceSemanticAgent"
    version = "semantic-rule-v1"

    async def handle(self, message: AgentMessage) -> AgentResult[dict[str, object]]:
        constraints = message.payload.get("constraints", {})
        degraded = isinstance(constraints, dict) and bool(constraints.get("force_degraded"))
        coverage = 0.25 if degraded else 0.84
        return _result(
            message,
            agent_name=self.name,
            agent_version=self.version,
            payload={
                "metadata_coverage": coverage,
                "vector_coverage": 0.0,
                "kg_path_coverage": 0.0,
                "required_slots": [],
                "dependency_status": {"MYSQL": "READY", "VECTOR": "DISABLED", "GRAPH": "DISABLED"},
            },
            confidence=coverage,
            warnings=("VECTOR_CHANNEL_UNAVAILABLE", "KG_CHANNEL_UNAVAILABLE") if degraded else (),
            fallback_used=degraded,
            decision=AgentDecision(
                action=AgentActionType.DEGRADE if degraded else AgentActionType.PROBE_RESOURCES,
                target="RecommendationPolicyAgent",
                reason_code="INDEX_CHANNEL_UNAVAILABLE" if degraded else "RESOURCE_PROBE_READY",
                confidence=coverage,
            ),
        )


class RuleRecommendationPolicyAgent:
    name = "RecommendationPolicyAgent"
    version = "policy-rule-v1"

    @staticmethod
    def _difficulty_level_count(constraints: dict[str, object]) -> int | None:
        """Read only an explicit coverage summary; never invent stages."""

        value = constraints.get("covered_difficulty_levels")
        if value is None:
            value = constraints.get("difficulty_levels")
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value >= 0 else None
        if isinstance(value, (list, tuple)):
            normalized = {
                str(item).strip().upper()
                for item in value
                if isinstance(item, str) and item.strip()
            }
            return len(normalized)
        return None

    async def handle(self, message: AgentMessage) -> AgentResult[dict[str, object]]:
        intent = message.payload.get("intent", {})
        profile = message.payload.get("profile", {})
        probe = message.payload.get("probe", {})
        constraints = message.payload.get("constraints", {})
        unclear = isinstance(intent, dict) and intent.get("intent_type") == "UNCLEAR"
        constraint_map = constraints if isinstance(constraints, dict) else {}
        intent_type = intent.get("intent_type", "GENERAL_RECOMMENDATION") if isinstance(intent, dict) else "GENERAL_RECOMMENDATION"
        topic_focus_strength = (
            profile.get("topic_focus_strength", profile.get("interest_strength", 0.0))
            if isinstance(profile, dict)
            else 0.0
        )
        explicit_output_type = message.payload.get("output_type")
        proposed_output_type = infer_auto_output_type(
            intent_type=intent_type,
            topic_focus_strength=topic_focus_strength,
            topic_focus_infer_threshold=constraint_map.get(
                "topic_focus_infer_threshold", DEFAULT_TOPIC_FOCUS_INFER_THRESHOLD
            ),
        )
        stability = stabilize_output_type(
            proposed_output_type=proposed_output_type,
            topic_focus_strength=topic_focus_strength,
            previous_output_type=constraint_map.get("previous_output_type"),
            previous_rounds=constraint_map.get("previous_output_type_rounds", 0),
            explicit_output_type=explicit_output_type,
            topic_focus_infer_threshold=constraint_map.get(
                "topic_focus_infer_threshold", DEFAULT_TOPIC_FOCUS_INFER_THRESHOLD
            ),
            hysteresis_margin=constraint_map.get(
                "hysteresis_margin", DEFAULT_HYSTERESIS_MARGIN
            ),
            min_output_type_rounds=constraint_map.get(
                "min_output_type_rounds", DEFAULT_MIN_OUTPUT_TYPE_ROUNDS
            ),
        )
        covered_difficulty_levels = self._difficulty_level_count(constraint_map)
        reading_path_single_level = (
            stability.output_type == "READING_PATH"
            and covered_difficulty_levels is not None
            and covered_difficulty_levels < 2
        )
        dependency_degraded = (
            bool(constraint_map.get("force_degraded"))
        ) or float(probe.get("metadata_coverage", 1.0) if isinstance(probe, dict) else 1.0) < 0.5
        degraded = dependency_degraded or reading_path_single_level
        policy_warnings: list[str] = []
        if dependency_degraded:
            policy_warnings.extend(("VECTOR_CHANNEL_UNAVAILABLE", "KG_CHANNEL_UNAVAILABLE"))
        if reading_path_single_level:
            policy_warnings.append("READING_PATH_SINGLE_DIFFICULTY")
        reason_codes = [stability.reason_code]
        if reading_path_single_level:
            reason_codes.append("READING_PATH_SINGLE_DIFFICULTY")
        reason_codes.append(
            "MYSQL_ONLY_FALLBACK"
            if dependency_degraded
            else "READING_PATH_DEGRADED"
            if reading_path_single_level
            else "DIRECT_PATH"
        )
        if unclear:
            return _result(
                message,
                agent_name=self.name,
                agent_version=self.version,
                payload={
                    "output_type": stability.output_type,
                    "delivery_strategy": "GUIDED",
                    "explanation_level": "LIMITED",
                    "adaptation_state": "NORMAL",
                    "decision_reason_codes": [
                        stability.reason_code,
                        "MISSING_REQUIRED_SLOTS",
                    ],
                    "decision_reason": "当前主题和资源类型不足以形成可靠推荐。",
                    "policy_version": self.version,
                    "output_type_rounds": stability.rounds,
                    "output_type_changed": stability.changed,
                    "explicit_output_type_override": stability.explicit_override,
                    "retrieval_plan": None,
                    "clarification_questions": [
                        {
                            "slot": "resource_types",
                            "question": "你更需要图书、论文，还是两者都需要？",
                            "options": ["BOOK", "PAPER", "BOOK_AND_PAPER"],
                            "required": True,
                        },
                        {
                            "slot": "topic",
                            "question": "你主要关注哪个主题？",
                            "options": ["多智能体", "推荐系统", "知识图谱"],
                            "required": True,
                        },
                    ],
                },
                confidence=0.9,
                decision=AgentDecision(
                    action=AgentActionType.ASK_CLARIFICATION,
                    target="User",
                    reason_code="MISSING_REQUIRED_SLOTS",
                    confidence=0.9,
                ),
            )
        delivery = "DEGRADED" if degraded else "DIRECT"
        return _result(
            message,
            agent_name=self.name,
            agent_version=self.version,
            payload={
                "output_type": stability.output_type,
                "delivery_strategy": delivery,
                "explanation_level": "LIMITED" if degraded else "EVIDENCE",
                "adaptation_state": "NORMAL",
                "decision_reason_codes": reason_codes,
                "decision_reason": (
                    "阅读路径仅覆盖一个难度层，降级返回，不伪造其他学习阶段。"
                    if reading_path_single_level
                    else "可选检索通道不可用，使用 MySQL 可复现降级路径。"
                    if degraded
                    else "输入和资源覆盖满足直接推荐条件。"
                ),
                "policy_version": self.version,
                "output_type_rounds": stability.rounds,
                "output_type_changed": stability.changed,
                "explicit_output_type_override": stability.explicit_override,
                "retrieval_plan": {
                    "plan_version": 1,
                    "min_candidates": 5,
                    "resource_quotas": {"BOOK": 3, "PAPER": 2},
                    "channels": ["PROFILE", "KEYWORD", "TRENDING"],
                },
                "clarification_questions": [],
            },
            confidence=0.62 if degraded else 0.88,
            warnings=tuple(policy_warnings),
            fallback_used=degraded,
            decision=AgentDecision(
                action=AgentActionType.DEGRADE if degraded else AgentActionType.PLAN_RECALL,
                target="CandidateRecallAgent",
                reason_code="DEGRADED_POLICY" if degraded else "RECALL_PLAN_READY",
                confidence=0.62 if degraded else 0.88,
            ),
        )


class RuleCandidateRecallAgent:
    name = "CandidateRecallAgent"
    version = "recall-rule-v1"

    async def handle(self, message: AgentMessage) -> AgentResult[dict[str, object]]:
        constraints = message.payload.get("constraints", {})
        limit = int(message.payload.get("limit", 5))
        degraded = isinstance(constraints, dict) and bool(constraints.get("force_degraded"))
        count = max(1, min(limit, limit // 2 if degraded else limit))
        candidates = [
            {
                "resource_id": index,
                "channel": "MYSQL",
                "score": round(1.0 - index / max(10, count + 1), 4),
                "evidence_ref": f"catalog:resource:{index}",
            }
            for index in range(1, count + 1)
        ]
        return _result(
            message,
            agent_name=self.name,
            agent_version=self.version,
            payload={"candidates": candidates, "candidate_count": len(candidates), "channels": ["MYSQL"]},
            confidence=0.55 if degraded else 0.86,
            status=AgentResultStatus.PARTIAL if degraded else AgentResultStatus.SUCCESS,
            warnings=("INSUFFICIENT_RESOURCE_COVERAGE",) if degraded else (),
            fallback_used=degraded,
            decision=AgentDecision(
                action=AgentActionType.DEGRADE if degraded else AgentActionType.SELECT_CHANNELS,
                target="RankingAgent",
                reason_code="INSUFFICIENT_RESOURCE_COVERAGE" if degraded else "MYSQL_CHANNEL_SELECTED",
                confidence=0.55 if degraded else 0.86,
            ),
        )


class RuleRankingAgent:
    name = "RankingAgent"
    version = "ranking-rule-v1"

    async def handle(self, message: AgentMessage) -> AgentResult[dict[str, object]]:
        constraints = message.payload.get("constraints", {})
        replan_count = int(message.payload.get("replan_count", 0))
        candidates = list(message.payload.get("candidates", []))
        force_replan = isinstance(constraints, dict) and bool(constraints.get("force_replan"))
        if force_replan and replan_count == 0:
            return _result(
                message,
                agent_name=self.name,
                agent_version=self.version,
                payload={"ranked_items": [], "replan_required": True, "replan_reason": "COVERAGE_BELOW_THRESHOLD"},
                confidence=0.45,
                status=AgentResultStatus.PARTIAL,
                warnings=("REPLAN_REQUIRED",),
                decision=AgentDecision(
                    action=AgentActionType.REQUEST_REPLAN,
                    target="RecommendationPolicyAgent",
                    reason_code="COVERAGE_BELOW_THRESHOLD",
                    confidence=0.45,
                ),
            )
        ranked = [
            {**candidate, "rank_no": index}
            for index, candidate in enumerate(
                sorted(candidates, key=lambda item: (-float(item.get("score", 0.0)), int(item.get("resource_id", 0)))),
                start=1,
            )
        ]
        return _result(
            message,
            agent_name=self.name,
            agent_version=self.version,
            payload={"ranked_items": ranked, "replan_required": False},
            confidence=0.82,
            decision=AgentDecision(
                action=AgentActionType.RETURN_RESULT,
                target="ExplanationAgent",
                reason_code="RANKING_READY",
                confidence=0.82,
            ),
        )


class RuleExplanationAgent:
    name = "ExplanationAgent"
    version = "explanation-rule-v1"

    async def handle(self, message: AgentMessage) -> AgentResult[dict[str, object]]:
        items = list(message.payload.get("ranked_items", []))
        explanations = [
            {
                "resource_id": int(item["resource_id"]),
                "rank_no": int(item["rank_no"]),
                "summary": "基于主题、画像和 MySQL 目录证据推荐。",
                "evidence_refs": [str(item.get("evidence_ref", "catalog:unknown"))],
            }
            for item in items
        ]
        return _result(
            message,
            agent_name=self.name,
            agent_version=self.version,
            payload={"explanations": explanations, "provider": "TEMPLATE"},
            confidence=0.84 if explanations else 0.5,
            warnings=("LIMITED_EVIDENCE",) if not explanations else (),
            decision=AgentDecision(
                action=AgentActionType.RENDER_EVIDENCE if explanations else AgentActionType.FALLBACK,
                target="RecommendationOrchestrator",
                reason_code="EVIDENCE_RENDERED" if explanations else "NO_RANKED_ITEMS",
                confidence=0.84 if explanations else 0.5,
            ),
        )


class RuleFeedbackLearningAgent:
    name = "FeedbackLearningAgent"
    version = "feedback-rule-v1"

    async def handle(self, message: AgentMessage) -> AgentResult[dict[str, object]]:
        return _result(
            message,
            agent_name=self.name,
            agent_version=self.version,
            payload={"delta": None, "outbox_required": False},
            confidence=0.5,
            status=AgentResultStatus.PARTIAL,
            warnings=("FEEDBACK_NOT_IN_G4_SLICE",),
            fallback_used=True,
        )


DEFAULT_RULE_AGENTS: tuple[Agent, ...] = (
    RuleIntentUnderstandingAgent(),
    RuleUserProfileAgent(),
    RuleResourceSemanticAgent(),
    RuleRecommendationPolicyAgent(),
    RuleCandidateRecallAgent(),
    RuleRankingAgent(),
    RuleExplanationAgent(),
    RuleFeedbackLearningAgent(),
)


__all__ = [
    "DEFAULT_RULE_AGENTS",
    "RuleCandidateRecallAgent",
    "RuleExplanationAgent",
    "RuleFeedbackLearningAgent",
    "RuleIntentUnderstandingAgent",
    "RuleRankingAgent",
    "RuleRecommendationPolicyAgent",
    "RuleResourceSemanticAgent",
    "RuleUserProfileAgent",
]
