"""Deterministic text rules shared by recommendation intent agents.

These helpers belong to the recommendation domain rather than to a concrete
Agent implementation.  Keeping them here prevents Agent-to-Agent imports while
preserving identical rule and LLM fallback behaviour.
"""

from __future__ import annotations

import re


GUIDED_CLARIFICATION_MARKERS = (
    "不确定",
    "不清楚",
    "不知道",
    "没想好",
    "没有想好",
    "梳理方向",
    "先帮我梳理",
    "还没有明确",
)

_TERM_BOUNDARY = re.compile(r"\s+|[,，、;；|/]+|以及|与|和|及")
_TRIM_CHARS = " \t\r\n,，、;；|/"


def looks_like_guided_clarification(text: str) -> bool:
    """Return whether *text* explicitly asks for help narrowing its goal."""

    normalized = "".join(text.split()).lower()
    return any(marker.lower() in normalized for marker in GUIDED_CLARIFICATION_MARKERS)


def extract_topic_terms(input_text: str | None) -> tuple[str, ...]:
    """Return stable, non-empty terms without calling a model or a store."""

    text = str(input_text or "").strip()
    if not text:
        return ()
    terms = {
        piece.strip(_TRIM_CHARS)
        for piece in _TERM_BOUNDARY.split(text)
        if piece.strip(_TRIM_CHARS)
    }
    return tuple(sorted(terms))


__all__ = [
    "GUIDED_CLARIFICATION_MARKERS",
    "extract_topic_terms",
    "looks_like_guided_clarification",
]
