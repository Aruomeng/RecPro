"""Dependency-free input, feature, and output values for G3."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ProfileSignal:
    tag_id: int
    weight: float
    negative: bool = False


@dataclass(frozen=True, slots=True)
class RecommendationRequest:
    user_id: int
    input_text: str | None
    resource_types: tuple[str, ...]
    limit: int
    evaluation_at: datetime
    output_type: str = "TOPIC_RESOURCES"


@dataclass(frozen=True, slots=True)
class IntentResult:
    intent_type: str
    confidence: float
    topic_terms: tuple[str, ...]
    resource_types: tuple[str, ...]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateFeature:
    resource: Any
    tags: tuple[Any, ...]
    channel_ranks: Mapping[str, int]
    channel_scores: Mapping[str, float]
    rrf_score: float
    final_score: float
    negative_penalty: float
    evidence_confidence: float
    primary_channel: str
    diversity_relaxed: bool = False


@dataclass(frozen=True, slots=True)
class RecommendationItemResult:
    rank_no: int
    feature: CandidateFeature
    explanation: str
    evidence_refs: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class RecommendationExecution:
    intent: IntentResult
    items: tuple[RecommendationItemResult, ...]
    warnings: tuple[str, ...] = ()
    decision_reason_codes: tuple[str, ...] = field(default_factory=tuple)
    trace_steps: tuple[dict[str, object], ...] = field(default_factory=tuple)
