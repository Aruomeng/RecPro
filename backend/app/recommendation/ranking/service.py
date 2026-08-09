"""Deterministic RRF and bounded diversity ranking."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from backend.app.recommendation.domain.public import CandidateFeature


def _author_key(feature: CandidateFeature) -> str:
    return feature.resource.authors[0] if feature.resource.authors else "__unknown__"


def _primary_tag(feature: CandidateFeature) -> int | None:
    return min((tag.tag_id for tag in feature.tags), default=None)


def rank_candidates(
    candidates: Iterable[CandidateFeature],
    *,
    limit: int,
    max_same_author: int = 2,
    max_same_primary_tag: int = 4,
) -> tuple[CandidateFeature, ...]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    ordered = sorted(
        candidates,
        key=lambda item: (-item.final_score, -item.rrf_score, item.resource.id),
    )
    author_counts: defaultdict[str, int] = defaultdict(int)
    tag_counts: defaultdict[int, int] = defaultdict(int)
    selected: list[CandidateFeature] = []
    deferred: list[CandidateFeature] = []
    for feature in ordered:
        author = _author_key(feature)
        primary_tag = _primary_tag(feature)
        if author_counts[author] >= max_same_author or (
            primary_tag is not None and tag_counts[primary_tag] >= max_same_primary_tag
        ):
            deferred.append(feature)
            continue
        selected.append(feature)
        author_counts[author] += 1
        if primary_tag is not None:
            tag_counts[primary_tag] += 1
        if len(selected) == limit:
            return tuple(selected)
    for feature in deferred:
        if len(selected) == limit:
            break
        selected.append(
            CandidateFeature(
                resource=feature.resource,
                tags=feature.tags,
                channel_ranks=feature.channel_ranks,
                channel_scores=feature.channel_scores,
                rrf_score=feature.rrf_score,
                final_score=feature.final_score,
                negative_penalty=feature.negative_penalty,
                evidence_confidence=feature.evidence_confidence,
                primary_channel=feature.primary_channel,
                diversity_relaxed=True,
            )
        )
    return tuple(selected)
