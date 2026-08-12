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
    agent_name: str = "IntentUnderstandingAgent",
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
        result_id=uuid5(message.message_id, f"result:{agent_name}:{message.attempt}"),
        input_message_id=message.message_id,
        agent_name=agent_name,
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
                agent_name=self.name,
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
                agent_name=self.name,
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
                agent_name=self.name,
                version="intent-rule-fallback-v1",
                payload=payload,
                confidence=min(confidence, 0.62),
                evidence_ref="rule:intent-fallback-v1",
                warnings=("LLM_INTENT_FALLBACK",),
                fallback_used=True,
                status=AgentResultStatus.PARTIAL,
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

    def __init__(self, provider: TextCapabilityProvider) -> None:
        self._provider = provider

    async def handle(self, message: AgentMessage) -> AgentResult[dict[str, object]]:
        raw_items = message.payload.get("ranked_items", [])
        if not isinstance(raw_items, list):
            raw_items = []
        explanations: list[dict[str, object]] = []
        fallback_used = False
        warnings: list[str] = []
        attempts = 0
        for raw_item in raw_items:
            item = dict(raw_item) if isinstance(raw_item, dict) else {}
            resource_id = int(item.get("resource_id", 0))
            rank_no = int(item.get("rank_no", len(explanations) + 1))
            allowed_refs = [
                str(item.get("evidence_ref", "")).strip()
            ] if str(item.get("evidence_ref", "")).strip() else []
            fallback_text, fallback_refs = _template_explanation(item)
            try:
                timeout = 5.0
                if message.deadline_at is not None:
                    timeout = max(
                        0.001,
                        (message.deadline_at - datetime.now(UTC)).total_seconds(),
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
                attempts += max(1, int(llm_result.attempts))
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
                explanations.append(
                    {
                        "resource_id": resource_id,
                        "rank_no": rank_no,
                        "summary": text.strip(),
                        "evidence_refs": list(refs),
                    }
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                fallback_used = True
                warnings.append("LLM_EXPLANATION_FALLBACK")
                warnings.append("EVIDENCE_VALIDATION_FAILED")
                explanations.append(
                    {
                        "resource_id": resource_id,
                        "rank_no": rank_no,
                        "summary": fallback_text,
                        "evidence_refs": fallback_refs,
                    }
                )
        unique_warnings = tuple(dict.fromkeys(warnings))
        return _result(
            message,
            agent_name=self.name,
            version=self.version if not fallback_used else "explanation-template-fallback-v1",
            payload={"explanations": explanations, "provider": "DEEPSEEK" if not fallback_used else "TEMPLATE"},
            confidence=0.78 if explanations and not fallback_used else 0.55,
            evidence_ref="rule:explanation-template-fallback-v1" if fallback_used else "llm:explanation.render",
            warnings=unique_warnings,
            fallback_used=fallback_used,
            status=AgentResultStatus.PARTIAL if fallback_used else AgentResultStatus.SUCCESS,
        )


__all__ = ["LLMExplanationAgent", "LLMIntentUnderstandingAgent"]
