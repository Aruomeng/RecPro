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
    # Audit metadata identifies the reviewed template without retaining the
    # rendered user text.  ``request_id`` is intentionally optional so the
    # deterministic Mock provider remains byte-for-byte reproducible.
    prompt_id: str | None = None
    prompt_sha256: str | None = None
    request_id: str | None = None
    attempts: int = 1


class TextCapabilityProvider(Protocol):
    async def classify_intent(self, text: str) -> LLMResult: ...

    async def parse_feedback_text(self, text: str) -> LLMResult: ...

    async def render_explanation(self, evidence: Mapping[str, Any]) -> LLMResult: ...

    async def render_group_summary(self, topic_name: str) -> LLMResult: ...
