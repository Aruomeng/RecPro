"""Deterministic historical input selection for evaluation-time replay.

The selector is deliberately storage-independent.  Callers provide immutable
facts already read through an adapter, and this module filters every fact by
the frozen ``evaluation_at`` boundary before calculating a content hash.  It
therefore cannot accidentally use a current projection or a future popularity
snapshot during an offline experiment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Iterable


def _aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class HistoricalResourceFact:
    resource_id: int
    available_from: datetime
    metadata_version: str

    def __post_init__(self) -> None:
        if self.resource_id < 1:
            raise ValueError("resource_id must be positive")
        _aware(self.available_from, "available_from")
        if not self.metadata_version.strip():
            raise ValueError("metadata_version must not be blank")


@dataclass(frozen=True, slots=True)
class HistoricalBehaviorFact:
    event_id: int
    occurred_at: datetime
    event_type: str
    resource_id: int | None

    def __post_init__(self) -> None:
        if self.event_id < 1:
            raise ValueError("event_id must be positive")
        _aware(self.occurred_at, "occurred_at")
        if not self.event_type.strip():
            raise ValueError("event_type must not be blank")


@dataclass(frozen=True, slots=True)
class HistoricalStateFact:
    resource_id: int
    state_type: str
    effective_at: datetime
    state_version: int

    def __post_init__(self) -> None:
        if self.resource_id < 1 or self.state_version < 1:
            raise ValueError("resource_id and state_version must be positive")
        if not self.state_type.strip():
            raise ValueError("state_type must not be blank")
        _aware(self.effective_at, "effective_at")


@dataclass(frozen=True, slots=True)
class HistoricalPopularityFact:
    resource_id: int
    cutoff_at: datetime
    popularity_score: float

    def __post_init__(self) -> None:
        if self.resource_id < 1:
            raise ValueError("resource_id must be positive")
        _aware(self.cutoff_at, "cutoff_at")
        if not 0.0 <= self.popularity_score <= 1.0:
            raise ValueError("popularity_score must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class HistoricalReplaySnapshot:
    evaluation_at: datetime
    resources: tuple[HistoricalResourceFact, ...]
    behaviors: tuple[HistoricalBehaviorFact, ...]
    states: tuple[HistoricalStateFact, ...]
    popularity: tuple[HistoricalPopularityFact, ...]
    content_hash: str


def _iso(value: datetime) -> str:
    return value.astimezone(value.tzinfo).isoformat()


def _canonical(snapshot: dict[str, object]) -> bytes:
    return json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def build_historical_replay_snapshot(
    *,
    evaluation_at: datetime,
    resources: Iterable[HistoricalResourceFact],
    behaviors: Iterable[HistoricalBehaviorFact],
    states: Iterable[HistoricalStateFact],
    popularity: Iterable[HistoricalPopularityFact],
) -> HistoricalReplaySnapshot:
    """Select only facts visible at ``evaluation_at`` and hash the selection."""

    _aware(evaluation_at, "evaluation_at")
    visible_resources = tuple(
        sorted(
            (fact for fact in resources if fact.available_from <= evaluation_at),
            key=lambda fact: (fact.resource_id, fact.available_from, fact.metadata_version),
        )
    )
    visible_behaviors = tuple(
        sorted(
            (fact for fact in behaviors if fact.occurred_at <= evaluation_at),
            key=lambda fact: (fact.occurred_at, fact.event_id, fact.event_type),
        )
    )
    visible_states = tuple(
        sorted(
            (fact for fact in states if fact.effective_at <= evaluation_at),
            key=lambda fact: (fact.resource_id, fact.effective_at, fact.state_version, fact.state_type),
        )
    )
    visible_popularity = tuple(
        sorted(
            (fact for fact in popularity if fact.cutoff_at <= evaluation_at),
            key=lambda fact: (fact.resource_id, fact.cutoff_at, fact.popularity_score),
        )
    )
    document = {
        "evaluation_at": _iso(evaluation_at),
        "resources": [
            {"resource_id": fact.resource_id, "available_from": _iso(fact.available_from), "metadata_version": fact.metadata_version}
            for fact in visible_resources
        ],
        "behaviors": [
            {"event_id": fact.event_id, "occurred_at": _iso(fact.occurred_at), "event_type": fact.event_type, "resource_id": fact.resource_id}
            for fact in visible_behaviors
        ],
        "states": [
            {"resource_id": fact.resource_id, "state_type": fact.state_type, "effective_at": _iso(fact.effective_at), "state_version": fact.state_version}
            for fact in visible_states
        ],
        "popularity": [
            {"resource_id": fact.resource_id, "cutoff_at": _iso(fact.cutoff_at), "popularity_score": fact.popularity_score}
            for fact in visible_popularity
        ],
    }
    content_hash = hashlib.sha256(_canonical(document)).hexdigest()
    return HistoricalReplaySnapshot(
        evaluation_at=evaluation_at,
        resources=visible_resources,
        behaviors=visible_behaviors,
        states=visible_states,
        popularity=visible_popularity,
        content_hash=content_hash,
    )


__all__ = [
    "HistoricalBehaviorFact",
    "HistoricalPopularityFact",
    "HistoricalReplaySnapshot",
    "HistoricalResourceFact",
    "HistoricalStateFact",
    "build_historical_replay_snapshot",
]
