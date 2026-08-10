"""Immutable state-transition audit values shared by bounded contexts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Mapping
from uuid import NAMESPACE_URL, UUID, uuid5


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def transition_uuid(
    *,
    aggregate_type: str,
    aggregate_id: str,
    transition_type: str,
    version_after: int,
    causation_ref: str,
) -> UUID:
    """Return a stable idempotency key for one logical state transition."""

    seed = "|".join(
        (
            aggregate_type,
            aggregate_id,
            transition_type,
            str(version_after),
            causation_ref,
        )
    )
    return uuid5(NAMESPACE_URL, f"libramas-state-transition:{seed}")


@dataclass(frozen=True, slots=True)
class StateTransition:
    """A versioned, append-only state change that must share its transaction."""

    transition_uuid: UUID
    module_name: str
    aggregate_type: str
    aggregate_id: str
    transition_type: str
    from_state: str | None
    to_state: str
    version_before: int | None
    version_after: int
    causation_ref: str
    actor_type: str
    actor_ref: str | None = None
    detail: Mapping[str, object] | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.transition_uuid, UUID):
            raise ValueError("transition_uuid must be a UUID")
        for field_name in (
            "module_name",
            "aggregate_type",
            "aggregate_id",
            "transition_type",
            "to_state",
            "causation_ref",
            "actor_type",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-blank string")
        if self.version_before is not None and self.version_before < 1:
            raise ValueError("version_before must be positive when present")
        if self.version_after < 1:
            raise ValueError("version_after must be positive")
        if self.version_before is not None and self.version_after <= self.version_before:
            raise ValueError("version_after must be greater than version_before")
        if self.version_before is None and self.version_after != 1:
            raise ValueError("first transition must use version_after=1")
        if self.actor_ref is not None and not self.actor_ref.strip():
            raise ValueError("actor_ref must be null or non-blank")
        if self.detail is not None:
            if not isinstance(self.detail, Mapping):
                raise ValueError("detail must be a mapping when present")
            object.__setattr__(self, "detail", MappingProxyType(dict(self.detail)))
        if self.created_at is not None:
            if not isinstance(self.created_at, datetime):
                raise ValueError("created_at must be a datetime when present")
            if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
                raise ValueError("created_at must be timezone-aware")

    def detail_json(self) -> str | None:
        return _canonical(dict(self.detail)) if self.detail is not None else None

    def created_at_utc(self) -> datetime:
        value = self.created_at or datetime.now(UTC)
        return value.astimezone(UTC).replace(tzinfo=None, microsecond=(value.microsecond // 1000) * 1000)


__all__ = ["StateTransition", "transition_uuid"]
