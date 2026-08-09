"""G3 deterministic MySQL-only recommendation use case."""

from __future__ import annotations

from collections import defaultdict

from backend.app.catalog.domain.public import ResourceSummary, ResourceTagEvidence
from backend.app.recommendation.application.intent import classify_intent
from backend.app.recommendation.domain.public import (
    CandidateFeature,
    ProfileSignal,
    RecommendationExecution,
    RecommendationItemResult,
    RecommendationRequest,
)
from backend.app.recommendation.explanation.service import render_explanation
from backend.app.recommendation.ranking.service import rank_candidates


CHANNEL_WEIGHTS = {"PROFILE": 0.35, "KEYWORD": 0.25, "TRENDING": 0.20}
RRF_K0 = 60.0
TOPIC_ALIASES = {
    "multi-agent": ("多智能体", "multi-agent"),
    "smart-library": ("智慧图书馆", "smart library"),
    "recommender-systems": ("推荐系统", "推荐算法", "recommender"),
    "research-methods": ("研究方法", "research method"),
    "knowledge-graph": ("知识图谱", "knowledge graph"),
}
BEHAVIOR_WEIGHT = {
    "VIEW_RESOURCE": 0.5,
    "FAVORITE_RESOURCE": 2.0,
    "BORROW_BOOK": 3.0,
    "RATE_HIGH": 2.0,
    "CLICK_RECOMMENDATION": 1.2,
}


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, value))


def _tokens(text: str | None) -> tuple[str, ...]:
    normalized = (text or "").strip().lower()
    if not normalized:
        return ()
    tokens = {normalized}
    for separator in (" ", ",", "，", "、", "/", "-", "_"):
        tokens.update(part for part in normalized.split(separator) if part)
    return tuple(sorted(tokens, key=lambda item: (-len(item), item)))


def _keyword_score(resource: ResourceSummary, tokens: tuple[str, ...]) -> float:
    if not tokens:
        return 0.0
    searchable = " ".join((resource.title, resource.abstract_text or "", *resource.keywords)).lower()
    matches = sum(1 for token in tokens if token in searchable)
    return _bounded(matches / max(1, len(tokens)))


def _profile_score(tags: tuple[ResourceTagEvidence, ...], profile: tuple[ProfileSignal, ...]) -> tuple[float, float]:
    positive = {signal.tag_id: signal.weight for signal in profile if not signal.negative}
    negative = {signal.tag_id: signal.weight for signal in profile if signal.negative}
    positive_score = sum(tag.weight * tag.confidence * positive.get(tag.tag_id, 0.0) for tag in tags)
    negative_score = sum(tag.weight * tag.confidence * negative.get(tag.tag_id, 0.0) for tag in tags)
    return _bounded(positive_score), _bounded(negative_score)


def _trending_score(resource_id: int, events: tuple[tuple[int, str], ...]) -> float:
    value = sum(BEHAVIOR_WEIGHT.get(event_type, 0.0) for event_resource_id, event_type in events if event_resource_id == resource_id)
    return _bounded(value / 4.0)


def execute_recommendation(
    request: RecommendationRequest,
    *,
    resources: tuple[ResourceSummary, ...],
    tags: tuple[ResourceTagEvidence, ...],
    profile_signals: tuple[ProfileSignal, ...] = (),
    behavior_events: tuple[tuple[int, str], ...] = (),
) -> RecommendationExecution:
    if request.limit < 1 or request.limit > 20:
        raise ValueError("limit must be between 1 and 20")
    intent = classify_intent(
        request.input_text,
        requested_resource_types=request.resource_types,
        requested_output_type=request.output_type,
    )
    tags_by_resource: dict[int, list[ResourceTagEvidence]] = defaultdict(list)
    for tag in tags:
        tags_by_resource[tag.resource_id].append(tag)
    candidates: list[CandidateFeature] = []
    tokens = tuple(
        dict.fromkeys(
            _tokens(request.input_text)
            + tuple(
                alias
                for topic in intent.topic_terms
                for alias in TOPIC_ALIASES.get(topic, ())
            )
        )
    )
    eligible_resources = tuple(
        resource
        for resource in resources
        if resource.resource_type in intent.resource_types and resource.available_from <= request.evaluation_at
    )
    for resource in eligible_resources:
        resource_tags = tuple(sorted(tags_by_resource.get(resource.id, ()), key=lambda item: item.tag_id))
        keyword_score = _keyword_score(resource, tokens)
        profile_score, negative_penalty = _profile_score(resource_tags, profile_signals)
        trending_score = _trending_score(resource.id, behavior_events)
        channel_scores = {"PROFILE": profile_score, "KEYWORD": keyword_score, "TRENDING": trending_score}
        channel_ranks: dict[str, int] = {}
        for channel in channel_scores:
            ranked = sorted(
                eligible_resources,
                key=lambda item: (
                    -(
                        _profile_score(tuple(tags_by_resource.get(item.id, ())), profile_signals)[0]
                        if channel == "PROFILE"
                        else _keyword_score(item, tokens)
                        if channel == "KEYWORD"
                        else _trending_score(item.id, behavior_events)
                    ),
                    item.id,
                ),
            )
            channel_ranks[channel] = next((index for index, item in enumerate(ranked, start=1) if item.id == resource.id), len(ranked) + 1)
        rrf_score = sum(CHANNEL_WEIGHTS[channel] * channel_scores[channel] / (RRF_K0 + channel_ranks[channel]) for channel in channel_scores)
        final_score = _bounded(0.50 * rrf_score * 60.0 + 0.30 * profile_score + 0.20 * keyword_score - 0.35 * negative_penalty)
        primary_channel = max(channel_scores, key=lambda channel: (channel_scores[channel], -channel_ranks[channel], channel))
        evidence_confidence = _bounded(0.55 * resource.metadata_quality + 0.25 * max(channel_scores.values()) + 0.20 * (1.0 - negative_penalty))
        candidates.append(
            CandidateFeature(
                resource=resource,
                tags=resource_tags,
                channel_ranks=channel_ranks,
                channel_scores=channel_scores,
                rrf_score=rrf_score,
                final_score=final_score,
                negative_penalty=negative_penalty,
                evidence_confidence=evidence_confidence,
                primary_channel=primary_channel,
            )
        )
    ranked = rank_candidates(candidates, limit=request.limit)
    items: list[RecommendationItemResult] = []
    for rank_no, feature in enumerate(ranked, start=1):
        explanation, refs = render_explanation(feature, intent)
        items.append(RecommendationItemResult(rank_no, feature, explanation, refs))
    warnings: tuple[str, ...] = ("INSUFFICIENT_RESOURCE_COVERAGE",) if len(items) < request.limit else ()
    reasons = intent.reason_codes + (("SUFFICIENT_RESOURCE_COVERAGE",) if len(items) >= request.limit else ("INSUFFICIENT_RESOURCE_COVERAGE",))
    trace_steps = (
        {"step": 1, "name": "RULE_INTENT", "status": "SUCCESS", "intent_type": intent.intent_type, "confidence": intent.confidence},
        {"step": 2, "name": "MYSQL_RECALL", "status": "SUCCESS", "candidate_count": len(candidates), "channels": ["PROFILE", "KEYWORD", "TRENDING"]},
        {"step": 3, "name": "RRF_RANKING_MMR", "status": "SUCCESS", "result_count": len(items)},
        {"step": 4, "name": "TEMPLATE_EXPLANATION", "status": "SUCCESS", "provider": "TEMPLATE"},
    )
    return RecommendationExecution(intent, tuple(items), warnings, reasons, trace_steps)
