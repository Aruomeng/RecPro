"""Deterministic, as-of profile replay functions with no storage dependency."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable


POSITIVE_EVENT_FACTORS: dict[str, float] = {
    "VIEW_RESOURCE": 0.5,
    "VIEW_EXPLANATION": 0.2,
    "CLICK_RECOMMENDATION": 0.8,
    "FAVORITE_RESOURCE": 1.0,
    "BORROW_BOOK": 1.2,
    "ACCESS_PAPER_FULLTEXT": 1.0,
    "RATE_HIGH": 1.1,
    "RATE_NEUTRAL": 0.2,
}
NEGATIVE_EVENT_FACTORS: dict[str, float] = {
    "NOT_INTERESTED": 1.0,
    "REJECT_RECOMMENDATION": 0.8,
}


@dataclass(frozen=True, slots=True)
class ResourceTagEvidence:
    tag_id: int
    weight: float
    confidence: float


@dataclass(frozen=True, slots=True)
class BehaviorForReplay:
    event_id: int
    event_uuid: str
    event_type: str
    resource_id: int | None
    occurred_at: datetime
    reason_code: str | None
    tags: tuple[ResourceTagEvidence, ...]


@dataclass(frozen=True, slots=True)
class InterestSignal:
    tag_id: int
    raw_signal: float
    weight: float
    source_count: int
    last_event_at: datetime


@dataclass(frozen=True, slots=True)
class NegativeSignal:
    tag_id: int
    reason_code: str
    raw_signal: float
    weight: float
    source_count: int
    last_event_at: datetime


@dataclass(frozen=True, slots=True)
class DeclaredProfileForReplay:
    """A consent-gated declared profile snapshot used by recommendation.

    This value intentionally lives in the profile bounded context instead of
    importing the IAM domain.  It is an as-of projection, and callers expose
    only its version/hash or derived tag IDs to Agent payloads.
    """

    declared_version: int
    major: str | None
    grade: str | None
    research_direction: str | None
    preferred_language: str | None
    personalization_enabled: bool
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ProfileSnapshot:
    user_id: int
    as_of: datetime
    formula_version: str
    event_count: int
    profile_confidence: float
    recent_focus_tag_id: int | None
    topic_focus_strength: float
    interests: tuple[InterestSignal, ...]
    negatives: tuple[NegativeSignal, ...]
    input_hash: str
    declared_profile_version: int | None = None
    declared_profile_hash: str | None = None
    declared_signals: tuple[InterestSignal, ...] = ()


def _bounded_weight(raw_signal: float) -> float:
    return max(0.0, min(1.0, raw_signal / (1.0 + raw_signal)))


def _effective_tag_weight(tag: ResourceTagEvidence) -> float:
    return max(0.0, min(1.0, tag.weight * tag.confidence))


def _canonical_event(event: BehaviorForReplay) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "event_uuid": event.event_uuid,
        "event_type": event.event_type,
        "resource_id": event.resource_id,
        "occurred_at": event.occurred_at.isoformat(),
        "reason_code": event.reason_code,
        "tags": [
            {"tag_id": tag.tag_id, "weight": tag.weight, "confidence": tag.confidence}
            for tag in event.tags
        ],
    }


def compute_profile_snapshot(
    *,
    user_id: int,
    as_of: datetime,
    events: Iterable[BehaviorForReplay],
    formula_version: str = "profile-g2-v1",
    declared_profile: DeclaredProfileForReplay | None = None,
    declared_signals: Iterable[InterestSignal] = (),
) -> ProfileSnapshot:
    """Compute a replay snapshot from facts at or before ``as_of``.

    The function is deterministic: event ordering, tag ordering, normalization,
    and the input digest are all stable. It never mutates a repository or filters
    facts by the time at which they were ingested.
    """

    eligible = tuple(
        sorted(
            (event for event in events if event.occurred_at <= as_of),
            key=lambda event: (event.occurred_at, event.event_id, event.event_uuid),
        )
    )
    positive_raw: dict[int, float] = {}
    positive_count: dict[int, int] = {}
    positive_last: dict[int, datetime] = {}
    negative_raw: dict[tuple[int, str], float] = {}
    negative_count: dict[tuple[int, str], int] = {}
    negative_last: dict[tuple[int, str], datetime] = {}

    for event in eligible:
        positive_factor = POSITIVE_EVENT_FACTORS.get(event.event_type, 0.0)
        negative_factor = NEGATIVE_EVENT_FACTORS.get(event.event_type, 0.0)
        for tag in event.tags:
            contribution = _effective_tag_weight(tag)
            if positive_factor:
                positive_raw[tag.tag_id] = positive_raw.get(tag.tag_id, 0.0) + contribution * positive_factor
                positive_count[tag.tag_id] = positive_count.get(tag.tag_id, 0) + 1
                positive_last[tag.tag_id] = max(positive_last.get(tag.tag_id, event.occurred_at), event.occurred_at)
            if negative_factor and event.reason_code == "TOPIC_NOT_INTERESTED":
                key = (tag.tag_id, event.reason_code)
                negative_raw[key] = negative_raw.get(key, 0.0) + contribution * negative_factor
                negative_count[key] = negative_count.get(key, 0) + 1
                negative_last[key] = max(negative_last.get(key, event.occurred_at), event.occurred_at)

    interests = tuple(
        InterestSignal(
            tag_id=tag_id,
            raw_signal=raw,
            weight=_bounded_weight(raw),
            source_count=positive_count[tag_id],
            last_event_at=positive_last[tag_id],
        )
        for tag_id, raw in sorted(positive_raw.items())
    )
    negatives = tuple(
        NegativeSignal(
            tag_id=tag_id,
            reason_code=reason_code,
            raw_signal=raw,
            weight=_bounded_weight(raw),
            source_count=negative_count[(tag_id, reason_code)],
            last_event_at=negative_last[(tag_id, reason_code)],
        )
        for (tag_id, reason_code), raw in sorted(negative_raw.items())
    )
    declared = tuple(
        sorted(
            (
                signal
                for signal in declared_signals
                if declared_profile is not None
                and declared_profile.personalization_enabled
                and isinstance(signal.tag_id, int)
                and not isinstance(signal.tag_id, bool)
                and signal.tag_id > 0
                and isinstance(signal.weight, (int, float))
                and not isinstance(signal.weight, bool)
                and math.isfinite(float(signal.weight))
                and 0.0 <= float(signal.weight) <= 1.0
            ),
            key=lambda signal: (signal.tag_id, -signal.weight),
        )
    )
    focus = max(interests, key=lambda signal: (signal.raw_signal, -signal.tag_id), default=None)
    declared_profile_hash: str | None = None
    declared_payload: dict[str, object] | None = None
    if declared_profile is not None:
        declared_payload = {
            "declared_version": declared_profile.declared_version,
            "major": declared_profile.major,
            "grade": declared_profile.grade,
            "research_direction": declared_profile.research_direction,
            "preferred_language": declared_profile.preferred_language,
            "personalization_enabled": declared_profile.personalization_enabled,
            "updated_at": declared_profile.updated_at.isoformat(),
        }
        declared_profile_hash = hashlib.sha256(
            json.dumps(
                declared_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    confidence = max(0.0, min(1.0, len(eligible) / 5.0))
    input_hash = hashlib.sha256(
        json.dumps(
            {
                "user_id": user_id,
                "as_of": as_of.isoformat(),
                "formula_version": formula_version,
                "events": [_canonical_event(event) for event in eligible],
                "declared_profile": declared_payload,
                "declared_signals": [
                    {
                        "tag_id": signal.tag_id,
                        "weight": signal.weight,
                        "source_count": signal.source_count,
                        "last_event_at": signal.last_event_at.isoformat(),
                    }
                    for signal in declared
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return ProfileSnapshot(
        user_id=user_id,
        as_of=as_of,
        formula_version=formula_version,
        event_count=len(eligible),
        profile_confidence=confidence,
        recent_focus_tag_id=focus.tag_id if focus else None,
        topic_focus_strength=focus.weight if focus else 0.0,
        interests=interests,
        negatives=negatives,
        input_hash=input_hash,
        declared_profile_version=(
            declared_profile.declared_version if declared_profile is not None else None
        ),
        declared_profile_hash=declared_profile_hash,
        declared_signals=declared,
    )
