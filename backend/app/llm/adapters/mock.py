"""Deterministic, key-free mock for G1 text-only capabilities."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from backend.app.llm.ports.public import LLMResult


class MockFailureMode(StrEnum):
    NORMAL = "NORMAL"
    TIMEOUT = "TIMEOUT"
    INVALID_PAYLOAD = "INVALID_PAYLOAD"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class MockLLMProvider:
    prompt_version: str = "mock-prompt-v1"
    failure_mode: MockFailureMode = MockFailureMode.NORMAL

    async def classify_intent(self, text: str) -> LLMResult:
        await self._apply_failure_mode()
        normalized = text.casefold()
        if "论文" in normalized or "paper" in normalized:
            intent = "PAPER_RECOMMENDATION"
        elif "图书" in normalized or "book" in normalized:
            intent = "BOOK_RECOMMENDATION"
        else:
            intent = "GENERAL_RECOMMENDATION"
        return self._result("intent.classify", {"intent": intent})

    async def parse_feedback_text(self, text: str) -> LLMResult:
        await self._apply_failure_mode()
        normalized = text.casefold()
        mappings = (
            (("太基础", "too basic"), "TOO_BASIC"),
            (("太难", "too advanced"), "TOO_ADVANCED"),
            (("读过", "already read"), "ALREADY_READ"),
            (("重复", "repeated"), "REPEATED"),
        )
        reason = next(
            (
                code
                for keywords, code in mappings
                if any(keyword in normalized for keyword in keywords)
            ),
            "OTHER",
        )
        return self._result("feedback.parse", {"reason_code": reason})

    async def render_explanation(self, evidence: Mapping[str, Any]) -> LLMResult:
        await self._apply_failure_mode()
        factors = evidence.get("factors", ())
        safe_factors = [str(item) for item in factors if str(item).strip()]
        text = "；".join(safe_factors) if safe_factors else "当前仅有有限的可验证证据。"
        return self._result(
            "explanation.render",
            {"text": text, "evidence_limited": not safe_factors},
        )

    async def render_group_summary(self, topic_name: str) -> LLMResult:
        await self._apply_failure_mode()
        topic = topic_name.strip() or "当前主题"
        return self._result(
            "group_summary.render", {"text": f"以下资源围绕{topic}整理。"}
        )

    async def _apply_failure_mode(self) -> None:
        if self.failure_mode is MockFailureMode.TIMEOUT:
            raise TimeoutError("mock provider timeout")
        if self.failure_mode is MockFailureMode.ERROR:
            raise RuntimeError("mock provider failure")
        if self.failure_mode is MockFailureMode.INVALID_PAYLOAD:
            raise ValueError("mock provider invalid payload")
        await asyncio.sleep(0)

    def _result(self, prompt_id: str, payload: Mapping[str, Any]) -> LLMResult:
        return LLMResult(
            provider="mock",
            model="mock-v1",
            prompt_version=self.prompt_version,
            payload=dict(payload),
            prompt_id=prompt_id,
        )
