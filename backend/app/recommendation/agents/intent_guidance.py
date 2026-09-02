"""Shared, deterministic detection for explicitly underspecified goals.

The rule and LLM intent Agents use the same conservative marker list so a
guided clarification request behaves consistently whether an LLM provider is
configured or the local fallback is active.  This module only classifies the
shape of user input; it never calls a provider and never extracts facts.
"""

from __future__ import annotations


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


def looks_like_guided_clarification(text: str) -> bool:
    """Return whether *text* explicitly asks for help narrowing its goal."""

    normalized = "".join(text.split()).lower()
    return any(marker.lower() in normalized for marker in GUIDED_CLARIFICATION_MARKERS)


__all__ = ["GUIDED_CLARIFICATION_MARKERS", "looks_like_guided_clarification"]
