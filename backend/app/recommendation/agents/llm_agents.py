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
from backend.app.recommendation.agents.base import Agent
from backend.app.shared_kernel.contracts.agent import AgentMessage, AgentResult
from backend.app.shared_kernel.contracts.enums import AgentResultStatus


def _result(
    message: AgentMessage,
    *,
    version: str,
    payload: dict[str, object],
    confidence: float,
    evidence_ref: str,
    warnings: tuple[str, ...] = (),
    fallback_used: bool = False,
    status: AgentResultStatus = AgentResultStatus.SUCCESS,
    error_code: str | None = None,
) -> AgentResult[dict[str, object]]:
    return AgentResult(
        result_id=uuid5(message.message_id, f"result:IntentUnderstandingAgent:{message.attempt}"),
        input_message_id=message.message_id,
        agent_name="IntentUnderstandingAgent",
        agent_version=version,
        status=status,
        confidence=max(0.0, min(1.0, confidence)),
        payload=payload,
        evidence_refs=(evidence_ref,),
        warnings=warnings,
        fallback_used=fallback_used,
        tool_calls=(),
        error_code=error_code,
        duration_ms=0,
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
    tokens = sorted({part for part in text.replace(",", " ").replace("，", " ").split() if part})
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
                version="intent-rule-fallback-v1",
                payload=payload,
                confidence=confidence,
                evidence_ref="rule:intent-fallback-v1",
                warnings=("LLM_INTENT_SKIPPED_EMPTY_INPUT",),
                fallback_used=True,
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
            tokens = sorted(
                {part for part in text.replace(",", " ").replace("，", " ").split() if part}
            )
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
                version=self.version,
                payload=payload,
                confidence=0.78,
                evidence_ref=audit_ref,
            )
        except asyncio.CancelledError:
            raise
        except (TimeoutError, RuntimeError, ValueError, OSError):
            payload, confidence = _rule_payload(message)
            return _result(
                message,
                version="intent-rule-fallback-v1",
                payload=payload,
                confidence=min(confidence, 0.62),
                evidence_ref="rule:intent-fallback-v1",
                warnings=("LLM_INTENT_FALLBACK",),
                fallback_used=True,
                status=AgentResultStatus.PARTIAL,
            )


__all__ = ["LLMIntentUnderstandingAgent"]
