"""Deterministic G4 Agent implementations used by the first orchestrator slice.

These Agents intentionally use only structured payloads.  They are replaceable
ports for later MySQL/vector/graph/LLM adapters and do not import one another.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid5

from backend.app.recommendation.agents.base import Agent
from backend.app.shared_kernel.contracts.agent import AgentMessage, AgentResult
from backend.app.shared_kernel.contracts.enums import AgentResultStatus


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
) -> AgentResult[dict[str, object]]:
    return AgentResult(
        result_id=uuid5(message.message_id, f"result:{agent_name}:{message.attempt}"),
        input_message_id=message.message_id,
        agent_name=agent_name,
        agent_version=agent_version,
        status=status,
        confidence=max(0.0, min(1.0, confidence)),
        payload=payload,
        evidence_refs=(f"rule:{agent_name}:{agent_version}",),
        warnings=warnings,
        fallback_used=fallback_used,
        tool_calls=(),
        error_code=error_code,
        duration_ms=0,
    )


class RuleIntentUnderstandingAgent:
    name = "IntentUnderstandingAgent"
    version = "intent-rule-v1"

    async def handle(self, message: AgentMessage) -> AgentResult[dict[str, object]]:
        text = str(message.payload.get("input_text") or "").strip()
        requested_types = [str(item) for item in message.payload.get("resource_types", [])]
        output_type = message.payload.get("output_type")
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
            )
        tokens = sorted({part for part in text.replace(",", " ").replace("，", " ").split() if part})
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
                "signals": [] if empty else ["TOPIC_HISTORY"],
            },
            confidence=confidence,
            warnings=("SESSION_ONLY_PROFILE",) if empty else (),
            fallback_used=empty,
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
        )


class RuleRecommendationPolicyAgent:
    name = "RecommendationPolicyAgent"
    version = "policy-rule-v1"

    async def handle(self, message: AgentMessage) -> AgentResult[dict[str, object]]:
        intent = message.payload.get("intent", {})
        probe = message.payload.get("probe", {})
        constraints = message.payload.get("constraints", {})
        unclear = isinstance(intent, dict) and intent.get("intent_type") == "UNCLEAR"
        degraded = (
            isinstance(constraints, dict) and bool(constraints.get("force_degraded"))
        ) or float(probe.get("metadata_coverage", 1.0) if isinstance(probe, dict) else 1.0) < 0.5
        if unclear:
            return _result(
                message,
                agent_name=self.name,
                agent_version=self.version,
                payload={
                    "output_type": "PERSONALIZED_FEED",
                    "delivery_strategy": "GUIDED",
                    "explanation_level": "LIMITED",
                    "adaptation_state": "NORMAL",
                    "decision_reason_codes": ["MISSING_REQUIRED_SLOTS"],
                    "decision_reason": "当前主题和资源类型不足以形成可靠推荐。",
                    "policy_version": self.version,
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
            )
        delivery = "DEGRADED" if degraded else "DIRECT"
        return _result(
            message,
            agent_name=self.name,
            agent_version=self.version,
            payload={
                "output_type": str(message.payload.get("output_type") or "TOPIC_RESOURCES"),
                "delivery_strategy": delivery,
                "explanation_level": "LIMITED" if degraded else "EVIDENCE",
                "adaptation_state": "NORMAL",
                "decision_reason_codes": ["MYSQL_ONLY_FALLBACK"] if degraded else ["DIRECT_PATH"],
                "decision_reason": "可选检索通道不可用，使用 MySQL 可复现降级路径。" if degraded else "输入和资源覆盖满足直接推荐条件。",
                "policy_version": self.version,
                "retrieval_plan": {
                    "plan_version": 1,
                    "min_candidates": 5,
                    "resource_quotas": {"BOOK": 3, "PAPER": 2},
                    "channels": ["PROFILE", "KEYWORD", "TRENDING"],
                },
                "clarification_questions": [],
            },
            confidence=0.62 if degraded else 0.88,
            warnings=("VECTOR_CHANNEL_UNAVAILABLE", "KG_CHANNEL_UNAVAILABLE") if degraded else (),
            fallback_used=degraded,
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
