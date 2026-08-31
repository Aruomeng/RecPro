"""Small, deterministic topic-term extraction shared by intent adapters."""

from __future__ import annotations

import re


# Chinese conjunctions are useful query boundaries in a kiosk sentence such
# as ``多智能体系统与智慧图书馆``.  Splitting them before the graph/vector
# ports are called keeps the raw user sentence intact for audit while giving
# each retrieval channel exact vocabulary terms.
_TERM_BOUNDARY = re.compile(r"\s+|[,，、;；|/]+|以及|与|和|及")
_TRIM_CHARS = " \t\r\n,，、;；|/"


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


__all__ = ["extract_topic_terms"]
