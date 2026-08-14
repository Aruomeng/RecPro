"""G3 deterministic MySQL-only recommendation use case."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, AsyncIterator, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

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
from backend.app.recommendation.domain.public import (
    RecommendationTaskCommand,
    RecommendationTaskResult,
)
from backend.app.recommendation.ports.public import (
    IdempotencyConflictError,
    RecommendationTaskService,
    StaleContextVersionError,
    TaskStateConflictError,
)

__all__ = [
    "IdempotencyConflictError",
    "RecommendationTaskService",
    "StaleContextVersionError",
    "TaskStateConflictError",
    "RecommendationTaskCommand",
    "RecommendationProgressBrokerPort",
    "RunCapacityError",
    "RunContextConflictError",
    "RunIdempotencyConflictError",
    "RunNotFoundError",
    "derive_task_identity_values",
    "execute_recommendation",
]


class RunCapacityError(RuntimeError):
    """The bounded research runtime cannot accept another active run."""


class RunNotFoundError(LookupError):
    """The run is absent, expired, or outside the caller's identity scope."""


class RunContextConflictError(RuntimeError):
    """A different or stale context is already active for this task."""


class RunIdempotencyConflictError(ValueError):
    """A run identity was reused with a different public request payload."""


class RecommendationProgressBrokerPort(Protocol):
    """Public application port used by the async HTTP adapter."""

    def reserve(self, *, task_id: UUID, trace_id: UUID, context_version: int, user_id: int, request_fingerprint: str) -> tuple[Any, bool]: ...
    def attach_task(self, task_id: UUID, task: Any) -> None: ...
    def complete(self, task_id: UUID, *, result: dict[str, object], replayed: bool) -> None: ...
    def fail(self, task_id: UUID, *, error_code: str) -> None: ...
    def state(self, task_id: UUID, *, user_id: int) -> dict[str, object]: ...
    def events(self, task_id: UUID, *, user_id: int, after_sequence: int = 0) -> AsyncIterator[dict[str, object] | None]: ...


def derive_task_identity_values(command: RecommendationTaskCommand) -> tuple[UUID, UUID]:
    """Return replay-stable task and trace IDs without infrastructure access."""

    return (
        uuid5(NAMESPACE_URL, f"task:{command.user_id}:{command.request_id}"),
        uuid5(NAMESPACE_URL, f"trace:{command.user_id}:{command.request_id}"),
    )


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
    resource_tags_by_id: dict[int, tuple[ResourceTagEvidence, ...]] = {}
    channel_scores_by_id: dict[str, dict[int, float]] = {
        "PROFILE": {},
        "KEYWORD": {},
        "TRENDING": {},
    }
    negative_penalty_by_id: dict[int, float] = {}
    for resource in eligible_resources:
        resource_tags = tuple(sorted(tags_by_resource.get(resource.id, ()), key=lambda item: item.tag_id))
        keyword_score = _keyword_score(resource, tokens)
        profile_score, negative_penalty = _profile_score(resource_tags, profile_signals)
        trending_score = _trending_score(resource.id, behavior_events)
        resource_tags_by_id[resource.id] = resource_tags
        negative_penalty_by_id[resource.id] = negative_penalty
        channel_scores_by_id["PROFILE"][resource.id] = profile_score
        channel_scores_by_id["KEYWORD"][resource.id] = keyword_score
        channel_scores_by_id["TRENDING"][resource.id] = trending_score

    # Each channel ranking is independent of the resource currently being
    # scored.  Build the three rank maps once instead of sorting the full
    # eligible catalog for every resource/channel pair (which was quadratic
    # in the real 15k-book dataset).
    channel_ranks_by_id: dict[str, dict[int, int]] = {}
    for channel, scores in channel_scores_by_id.items():
        ranked = sorted(
            eligible_resources,
            key=lambda item: (-scores[item.id], item.id),
        )
        channel_ranks_by_id[channel] = {
            item.id: index for index, item in enumerate(ranked, start=1)
        }

    for resource in eligible_resources:
        resource_tags = resource_tags_by_id[resource.id]
        profile_score = channel_scores_by_id["PROFILE"][resource.id]
        keyword_score = channel_scores_by_id["KEYWORD"][resource.id]
        trending_score = channel_scores_by_id["TRENDING"][resource.id]
        negative_penalty = negative_penalty_by_id[resource.id]
        channel_scores = {
            "PROFILE": profile_score,
            "KEYWORD": keyword_score,
            "TRENDING": trending_score,
        }
        channel_ranks = {
            channel: channel_ranks_by_id[channel][resource.id]
            for channel in channel_scores
        }
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
