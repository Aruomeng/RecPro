"""Opt-in LLM-backed Agents with deterministic, local fallbacks.

The LLM provider is a capability port.  This module does not know about HTTP,
database drivers, files, or SDKs, and it never lets model output create topic
terms or resource identifiers.  The orchestrator can replace the rule intent
Agent with this class only through an explicit composition argument.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid5

from backend.app.llm.ports.public import TextCapabilityProvider
from backend.app.shared_kernel.contracts.autonomy import (
    attach_decision,
    default_decision,
    validate_decision,
)
from backend.app.recommendation.agents.base import Agent
from backend.app.recommendation.agents.topic_terms import extract_topic_terms
from backend.app.shared_kernel.contracts.agent import AgentDecision, AgentMessage, AgentResult
from backend.app.shared_kernel.contracts.enums import AgentActionType, AgentResultStatus


def _result(
    message: AgentMessage,
    *,
    agent_name: str = "IntentUnderstandingAgent",
    version: str,
    payload: dict[str, object],
    confidence: float,
    evidence_ref: str,
    warnings: tuple[str, ...] = (),
    fallback_used: bool = False,
    status: AgentResultStatus = AgentResultStatus.SUCCESS,
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
        agent_version=version,
        status=status,
        confidence=max(0.0, min(1.0, confidence)),
        payload=attach_decision(dict(payload), resolved_decision),
        evidence_refs=(evidence_ref,),
        warnings=warnings,
        fallback_used=fallback_used,
        tool_calls=(),
        error_code=error_code,
        duration_ms=0,
        decision=resolved_decision,
    )


def _rule_payload(message: AgentMessage) -> tuple[dict[str, object], float]:
    text = str(message.payload.get("input_text") or "").strip()
    requested_types = [str(item) for item in message.payload.get("resource_types", [])]
    output_type = message.payload.get("output_type")
    if not text and not requested_types and output_type is None:
        return (
            {
                "intent_type": "UNCLEAR",
                "confidence": 0.2,
                "topic_terms": [],
                "resource_types": [],
                "reason_codes": ["MISSING_REQUIRED_SLOTS"],
            },
            0.2,
        )
    tokens = list(extract_topic_terms(text))
    return (
        {
            "intent_type": "TOPIC_RECOMMENDATION" if text else "GENERAL_RECOMMENDATION",
            "confidence": 0.86 if text else 0.58,
            "topic_terms": tokens,
            "resource_types": requested_types or ["BOOK", "PAPER"],
            "reason_codes": ["EXPLICIT_INPUT"] if text else ["DEFAULT_RESOURCE_TYPES"],
        },
        0.86 if text else 0.58,
    )


_GUIDED_CLARIFICATION_MARKERS = (
    "不确定",
    "不清楚",
    "不知道",
    "没想好",
    "没有想好",
    "梳理方向",
    "先帮我梳理",
    "还没有明确",
)


def _looks_like_guided_clarification(text: str) -> bool:
    """Detect an explicit lack of research direction before spending an LLM call."""

    normalized = "".join(text.split()).lower()
    return any(marker.lower() in normalized for marker in _GUIDED_CLARIFICATION_MARKERS)


def _intent_fallback_reason(exc: Exception) -> str:
    """Classify a provider failure without retaining provider text or prompts."""

    if isinstance(exc, TimeoutError):
        return "LLM_INTENT_TIMEOUT"
    if isinstance(exc, ValueError):
        # Includes bounded JSON/schema/allow-list validation failures.
        return "LLM_INTENT_OUTPUT_REJECTED"
    if isinstance(exc, OSError):
        return "LLM_INTENT_TRANSPORT_UNAVAILABLE"
    return "LLM_INTENT_PROVIDER_UNAVAILABLE"


class LLMIntentUnderstandingAgent:
    """Use the configured text capability for classification, never for facts."""

    name = "IntentUnderstandingAgent"
    version = "intent-llm-prompt-v1"

    def __init__(self, provider: TextCapabilityProvider) -> None:
        self._provider = provider

    async def handle(self, message: AgentMessage) -> AgentResult[dict[str, object]]:
        text = str(message.payload.get("input_text") or "").strip()
        if not text:
            payload, confidence = _rule_payload(message)
            return _result(
                message,
                agent_name=self.name,
                version="intent-rule-fallback-v1",
                payload=payload,
                confidence=confidence,
                evidence_ref="rule:intent-fallback-v1",
                warnings=("LLM_INTENT_SKIPPED_EMPTY_INPUT",),
                fallback_used=True,
                decision=AgentDecision(
                    action=AgentActionType.FALLBACK,
                    target="RecommendationOrchestrator",
                    reason_code="LLM_INTENT_SKIPPED_EMPTY_INPUT",
                    confidence=min(confidence, 0.62),
                ),
            )

        if _looks_like_guided_clarification(text):
            requested_types = [str(item) for item in message.payload.get("resource_types", [])]
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
                version="intent-guided-rule-v1",
                payload=payload,
                confidence=0.72,
                evidence_ref="rule:intent-guided-v1",
                warnings=("LLM_INTENT_SKIPPED_AMBIGUOUS_INPUT",),
                fallback_used=True,
                decision=AgentDecision(
                    action=AgentActionType.ASK_CLARIFICATION,
                    target="RecommendationOrchestrator",
                    reason_code="AMBIGUOUS_USER_GOAL",
                    confidence=0.72,
                ),
            )

        try:
            timeout = 5.0
            if message.deadline_at is not None:
                timeout = max(0.001, (message.deadline_at - datetime.now(UTC)).total_seconds())
            llm_result = await asyncio.wait_for(
                self._provider.classify_intent(text),
                timeout=timeout,
            )
            intent = llm_result.payload.get("intent")
            if intent not in {
                "BOOK_RECOMMENDATION",
                "PAPER_RECOMMENDATION",
                "GENERAL_RECOMMENDATION",
            }:
                raise ValueError("LLM intent payload is outside the allowlist")
            requested_types = [str(item) for item in message.payload.get("resource_types", [])]
            tokens = list(extract_topic_terms(text))
            payload = {
                "intent_type": "TOPIC_RECOMMENDATION"
                if intent != "GENERAL_RECOMMENDATION"
                else "GENERAL_RECOMMENDATION",
                "confidence": 0.78,
                "topic_terms": tokens,
                "resource_types": requested_types or ["BOOK", "PAPER"],
                "reason_codes": ["LLM_CLASSIFICATION"],
                "llm_provider": llm_result.provider,
                "prompt_version": llm_result.prompt_version,
                "prompt_id": llm_result.prompt_id,
                "prompt_sha256": llm_result.prompt_sha256,
                "llm_attempts": llm_result.attempts,
            }
            audit_ref = (
                f"llm:{llm_result.prompt_id or 'unknown'}:"
                f"{llm_result.prompt_sha256 or 'unhashed'}"
            )
            return _result(
                message,
                agent_name=self.name,
                version=self.version,
                payload=payload,
                confidence=0.78,
                evidence_ref=audit_ref,
                decision=AgentDecision(
                    action=AgentActionType.RETURN_RESULT,
                    target="RecommendationOrchestrator",
                    reason_code="LLM_CLASSIFICATION",
                    confidence=0.78,
                    evidence_refs=(audit_ref,),
                ),
            )
        except asyncio.CancelledError:
            raise
        except (TimeoutError, RuntimeError, ValueError, OSError) as exc:
            payload, confidence = _rule_payload(message)
            fallback_reason = _intent_fallback_reason(exc)
            payload["llm_fallback_reason_code"] = fallback_reason
            return _result(
                message,
                agent_name=self.name,
                version="intent-rule-fallback-v1",
                payload=payload,
                confidence=min(confidence, 0.62),
                evidence_ref="rule:intent-fallback-v1",
                warnings=("LLM_INTENT_FALLBACK", fallback_reason),
                fallback_used=True,
                status=AgentResultStatus.PARTIAL,
                decision=AgentDecision(
                    action=AgentActionType.FALLBACK,
                    target="RecommendationOrchestrator",
                    reason_code=fallback_reason,
                    confidence=min(confidence, 0.62),
                ),
            )


def _template_explanation(item: dict[str, object]) -> tuple[str, list[str]]:
    """Return a bounded explanation using only the item's supplied reference."""

    evidence_ref = str(item.get("evidence_ref", "")).strip()
    if not evidence_ref:
        return "当前仅有有限的可验证证据。", []
    return "基于已验证的目录证据生成推荐解释。", [evidence_ref]


class LLMExplanationAgent:
    """Render explanations through a provider with an evidence-only fallback."""

    name = "ExplanationAgent"
    version = "explanation-llm-prompt-v1"

    def __init__(self, provider: TextCapabilityProvider, *, max_concurrency: int = 4) -> None:
        if isinstance(max_concurrency, bool) or not 1 <= max_concurrency <= 8:
            raise ValueError("max_concurrency must be between 1 and 8")
        self._provider = provider
        self._max_concurrency = max_concurrency

    async def _render_item(
        self,
        raw_item: object,
        *,
        fallback_rank_no: int,
        deadline_at: datetime | None,
        semaphore: asyncio.Semaphore,
    ) -> tuple[dict[str, object], bool, tuple[str, ...], int]:
        item = dict(raw_item) if isinstance(raw_item, dict) else {}
        resource_id = int(item.get("resource_id", 0))
        rank_no = int(item.get("rank_no", fallback_rank_no))
        allowed_refs = [
            str(item.get("evidence_ref", "")).strip()
        ] if str(item.get("evidence_ref", "")).strip() else []
        fallback_text, fallback_refs = _template_explanation(item)
        try:
            async with semaphore:
                timeout = 5.0
                if deadline_at is not None:
                    timeout = max(
                        0.001,
                        (deadline_at - datetime.now(UTC)).total_seconds(),
                    )
                llm_result = await asyncio.wait_for(
                    self._provider.render_explanation(
                        {
                            "factors": [
                                f"召回通道：{item.get('channel', 'MYSQL')}",
                                f"排序位置：{rank_no}",
                            ],
                            "evidence_refs": allowed_refs,
                        }
                    ),
                    timeout=timeout,
                )
            attempts = max(1, int(llm_result.attempts))
            payload = llm_result.payload
            text = payload.get("text")
            refs = payload.get("evidence_refs")
            if (
                not isinstance(text, str)
                or not text.strip()
                or len(text.strip()) > 240
                or not isinstance(refs, list)
                or not refs
                or any(
                    not isinstance(ref, str)
                    or ref not in allowed_refs
                    or f"[{ref}]" not in text
                    for ref in refs
                )
            ):
                raise ValueError("LLM explanation failed evidence validation")
            return (
                {
                    "resource_id": resource_id,
                    "rank_no": rank_no,
                    "summary": text.strip(),
                    "evidence_refs": list(refs),
                },
                False,
                (),
                attempts,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return (
                {
                    "resource_id": resource_id,
                    "rank_no": rank_no,
                    "summary": fallback_text,
                    "evidence_refs": fallback_refs,
                },
                True,
                ("LLM_EXPLANATION_FALLBACK", "EVIDENCE_VALIDATION_FAILED"),
                0,
            )

    async def handle(self, message: AgentMessage) -> AgentResult[dict[str, object]]:
        raw_items = message.payload.get("ranked_items", [])
        if not isinstance(raw_items, list):
            raw_items = []
        semaphore = asyncio.Semaphore(self._max_concurrency)
        rendered = await asyncio.gather(
            *(
                self._render_item(
                    raw_item,
                    fallback_rank_no=index,
                    deadline_at=message.deadline_at,
                    semaphore=semaphore,
                )
                for index, raw_item in enumerate(raw_items, start=1)
            )
        )
        explanations = [item[0] for item in rendered]
        fallback_used = any(item[1] for item in rendered)
        warnings = [warning for item in rendered for warning in item[2]]
        attempts = sum(item[3] for item in rendered)
        unique_warnings = tuple(dict.fromkeys(warnings))
        return _result(
            message,
            agent_name=self.name,
            version=self.version if not fallback_used else "explanation-template-fallback-v1",
            payload={
                "explanations": explanations,
                "provider": "DEEPSEEK" if not fallback_used else "TEMPLATE",
                "llm_attempts": attempts,
            },
            confidence=0.78 if explanations and not fallback_used else 0.55,
            evidence_ref="rule:explanation-template-fallback-v1" if fallback_used else "llm:explanation.render",
            warnings=unique_warnings,
            fallback_used=fallback_used,
            status=AgentResultStatus.PARTIAL if fallback_used else AgentResultStatus.SUCCESS,
            decision=AgentDecision(
                action=AgentActionType.FALLBACK if fallback_used else AgentActionType.RENDER_EVIDENCE,
                target="RecommendationOrchestrator",
                reason_code="EVIDENCE_VALIDATION_FAILED" if fallback_used else "EVIDENCE_RENDERED",
                confidence=0.55 if fallback_used else 0.78,
            ),
        )


__all__ = ["LLMExplanationAgent", "LLMIntentUnderstandingAgent"]
