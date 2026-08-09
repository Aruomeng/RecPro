"""Deterministic rule intent resolution for the G3 baseline."""

from __future__ import annotations

from backend.app.recommendation.domain.public import IntentResult


TOPIC_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("multi-agent", ("多智能体", "multi-agent", "multi agent", "agentic")),
    ("smart-library", ("智慧图书馆", "smart library", "digital library")),
    ("recommender-systems", ("推荐系统", "推荐算法", "recommender", "recommendation system")),
    ("research-methods", ("研究方法", "实证", "evaluation", "research method")),
    ("knowledge-graph", ("知识图谱", "knowledge graph", "graph")),
)


def classify_intent(
    input_text: str | None,
    *,
    requested_resource_types: tuple[str, ...],
    requested_output_type: str | None = None,
) -> IntentResult:
    normalized = (input_text or "").strip().lower()
    topics = tuple(
        canonical
        for canonical, terms in TOPIC_TERMS
        if any(term.lower() in normalized for term in terms)
    )
    resource_types = tuple(requested_resource_types) or ("BOOK", "PAPER")
    if requested_output_type == "BOOKLIST":
        intent_type = "BOOKLIST_RECOMMENDATION"
        reason = ("EXPLICIT_BOOKLIST",)
    elif requested_output_type == "READING_PATH":
        intent_type = "READING_PATH_RECOMMENDATION"
        reason = ("EXPLICIT_READING_PATH",)
    elif topics and resource_types == ("PAPER",):
        intent_type = "PAPER_RECOMMENDATION"
        reason = ("EXPLICIT_TOPIC", "PAPER_RESOURCE_TYPE")
    elif topics and resource_types == ("BOOK",):
        intent_type = "BOOK_RECOMMENDATION"
        reason = ("EXPLICIT_TOPIC", "BOOK_RESOURCE_TYPE")
    elif topics:
        intent_type = "TOPIC_RECOMMENDATION"
        reason = ("EXPLICIT_TOPIC",)
    else:
        intent_type = "GENERAL_RECOMMENDATION"
        reason = ("RULE_INTENT_FALLBACK",)
    confidence = 0.9 if topics or requested_output_type else 0.55
    return IntentResult(
        intent_type=intent_type,
        confidence=confidence,
        topic_terms=topics,
        resource_types=resource_types,
        reason_codes=reason,
    )
