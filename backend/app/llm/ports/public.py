"""Typed boundary for evidence-constrained text capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True, slots=True)
class LLMResult:
    provider: str
    model: str
    prompt_version: str
    payload: Mapping[str, Any]


class TextCapabilityProvider(Protocol):
    async def classify_intent(self, text: str) -> LLMResult: ...

    async def parse_feedback_text(self, text: str) -> LLMResult: ...

    async def render_explanation(self, evidence: Mapping[str, Any]) -> LLMResult: ...

    async def render_group_summary(self, topic_name: str) -> LLMResult: ...
