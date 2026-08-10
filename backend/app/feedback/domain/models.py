"""Validated commands and receipts for the G5 feedback slice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from backend.app.shared_kernel.contracts.enums import (
    BehaviorEventType,
    FeedbackType,
    NegativeReasonCode,
)


def _aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _uuid(value: object, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise ValueError(f"{field_name} must be a UUID")


@dataclass(frozen=True, slots=True)
class ImpressionCommand:
    impression_uuid: UUID
    recommendation_item_id: int
    user_id: int
    position: int
    rendered_at: datetime
    visible_started_at: datetime | None = None
    visible_ms: int = 0
    max_visible_ratio: float = 0.0

    def __post_init__(self) -> None:
        _uuid(self.impression_uuid, "impression_uuid")
        if self.recommendation_item_id < 1 or self.user_id < 1:
            raise ValueError("recommendation_item_id and user_id must be positive")
        if self.position < 1:
            raise ValueError("position must be positive")
        if self.visible_ms < 0:
            raise ValueError("visible_ms must not be negative")
        if not 0 <= self.max_visible_ratio <= 1:
            raise ValueError("max_visible_ratio must be between 0 and 1")
        if self.visible_ms > 0 and self.visible_started_at is None:
            raise ValueError("visible_started_at is required when visible_ms is positive")
        _aware(self.rendered_at, "rendered_at")
        if self.visible_started_at is not None:
            _aware(self.visible_started_at, "visible_started_at")


@dataclass(frozen=True, slots=True)
class BehaviorAppendCommand:
    event_uuid: UUID
    user_id: int
    session_id: UUID
    event_type: BehaviorEventType
    occurred_at: datetime
    resource_id: int | None = None
    recommendation_item_id: int | None = None
    task_id: UUID | None = None
    impression_uuid: UUID | None = None
    query_text: str | None = None
    rating: float | None = None
    dwell_ms: int | None = None
    visible_ratio: float | None = None
    position: int | None = None
    reason_code: str | None = None
    tag_evidence: tuple[dict[str, Any], ...] = ()
    enqueue_profile_update: bool = True

    def __post_init__(self) -> None:
        _uuid(self.event_uuid, "event_uuid")
        _uuid(self.session_id, "session_id")
        if not isinstance(self.event_type, BehaviorEventType):
            raise ValueError("event_type must be a BehaviorEventType")
        if self.impression_uuid is not None:
            _uuid(self.impression_uuid, "impression_uuid")
        if self.task_id is not None:
            _uuid(self.task_id, "task_id")
        if self.user_id < 1:
            raise ValueError("user_id must be positive")
        if self.resource_id is not None and self.resource_id < 1:
            raise ValueError("resource_id must be positive")
        if self.recommendation_item_id is not None and self.recommendation_item_id < 1:
            raise ValueError("recommendation_item_id must be positive")
        if self.rating is not None and not 1 <= self.rating <= 5:
            raise ValueError("rating must be between 1 and 5")
        if self.dwell_ms is not None and self.dwell_ms < 0:
            raise ValueError("dwell_ms must not be negative")
        if self.visible_ratio is not None and not 0 <= self.visible_ratio <= 1:
            raise ValueError("visible_ratio must be between 0 and 1")
        if self.position is not None and self.position < 1:
            raise ValueError("position must be positive")
        _aware(self.occurred_at, "occurred_at")


@dataclass(frozen=True, slots=True)
class FeedbackCommand:
    feedback_uuid: UUID
    recommendation_item_id: int
    user_id: int
    feedback_type: FeedbackType
    occurred_at: datetime
    impression_uuid: UUID | None = None
    reason_code: NegativeReasonCode | None = None
    rating: float | None = None
    content: str | None = None

    def __post_init__(self) -> None:
        _uuid(self.feedback_uuid, "feedback_uuid")
        if not isinstance(self.feedback_type, FeedbackType):
            raise ValueError("feedback_type must be a FeedbackType")
        if self.recommendation_item_id < 1 or self.user_id < 1:
            raise ValueError("recommendation_item_id and user_id must be positive")
        if self.impression_uuid is not None:
            _uuid(self.impression_uuid, "impression_uuid")
        if self.reason_code is not None and not isinstance(self.reason_code, NegativeReasonCode):
            raise ValueError("reason_code must be a NegativeReasonCode")
        if self.rating is not None and not 1 <= self.rating <= 5:
            raise ValueError("rating must be between 1 and 5")
        if self.feedback_type is FeedbackType.RATE and self.rating is None:
            raise ValueError("RATE feedback requires rating")
        if self.feedback_type is not FeedbackType.RATE and self.rating is not None:
            raise ValueError("only RATE feedback accepts rating")
        if self.content is not None and len(self.content) > 1000:
            raise ValueError("content must be at most 1000 characters")
        _aware(self.occurred_at, "occurred_at")


@dataclass(frozen=True, slots=True)
class BehaviorReceipt:
    event_uuid: UUID
    event_id: int
    outbox_id: int | None
    replayed: bool


@dataclass(frozen=True, slots=True)
class ImpressionReceipt:
    impression_uuid: UUID
    impression_id: int
    behavior_event_id: int
    is_valid_exposure: bool
    replayed: bool


@dataclass(frozen=True, slots=True)
class FeedbackReceipt:
    feedback_uuid: UUID
    feedback_id: int
    behavior_event_id: int
    outbox_id: int | None
    resource_state: dict[str, object] | None
    replayed: bool


@dataclass(frozen=True, slots=True)
class ProfileRefreshReceipt:
    outbox_id: int
    user_id: int
    source_event_id: int
    profile_version: int
    event_count: int
    input_hash: str
    changed: bool


def feedback_event_type(command: FeedbackCommand) -> BehaviorEventType:
    if command.feedback_type is FeedbackType.FAVORITE:
        return BehaviorEventType.FAVORITE_RESOURCE
    if command.feedback_type is FeedbackType.BORROW:
        return BehaviorEventType.BORROW_BOOK
    if command.feedback_type is FeedbackType.REJECT:
        return BehaviorEventType.REJECT_RECOMMENDATION
    if command.feedback_type is FeedbackType.NOT_INTERESTED:
        return BehaviorEventType.NOT_INTERESTED
    assert command.rating is not None
    if command.rating >= 4:
        return BehaviorEventType.RATE_HIGH
    if command.rating <= 2:
        return BehaviorEventType.RATE_LOW
    return BehaviorEventType.RATE_NEUTRAL


__all__ = [
    "BehaviorAppendCommand",
    "BehaviorReceipt",
    "FeedbackCommand",
    "FeedbackReceipt",
    "ImpressionCommand",
    "ImpressionReceipt",
    "ProfileRefreshReceipt",
    "feedback_event_type",
]
