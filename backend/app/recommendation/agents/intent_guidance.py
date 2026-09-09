"""Shared, deterministic detection for explicitly underspecified goals.

The rule and LLM intent Agents use the same conservative marker list so a
guided clarification request behaves consistently whether an LLM provider is
configured or the local fallback is active.  This module only classifies the
shape of user input; it never calls a provider and never extracts facts.
"""

from backend.app.recommendation.domain.intent_text import (
    GUIDED_CLARIFICATION_MARKERS,
    looks_like_guided_clarification,
)


__all__ = ["GUIDED_CLARIFICATION_MARKERS", "looks_like_guided_clarification"]
