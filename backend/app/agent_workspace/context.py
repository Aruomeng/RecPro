"""Replaceable, read-only context providers for ambient Agent coordination."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Mapping, Protocol


@dataclass(frozen=True, slots=True)
class ContextObservation:
    source_id: str
    kind: str
    label: str
    status: str
    observed_at: datetime
    expires_at: datetime
    values: Mapping[str, object]


class ContextProvider(Protocol):
    """Read public context without performing business writes or LLM calls."""

    timeout_seconds: float

    def read(self, *, now: datetime) -> ContextObservation: ...


class LocalDemoExternalContextProvider:
    """Deterministic local stand-in for future library-owned external APIs."""

    timeout_seconds = 1.0

    def __init__(self, source_id: str) -> None:
        self._source_id = source_id
        self._cached: ContextObservation | None = None

    def read(self, *, now: datetime) -> ContextObservation:
        if self._cached is not None and self._cached.expires_at > now:
            return self._cached
        if self._source_id == "demo-library-schedule":
            label = "演示开放安排"
            values: Mapping[str, object] = {"timezone": "Asia/Shanghai", "opens_at": "08:00", "closes_at": "22:00"}
        elif self._source_id == "demo-academic-calendar":
            label = "演示学术日历"
            phase = "暑期准备期" if now.month in {7, 8} else "教学期"
            values = {"phase": phase, "suggested_topics": ["多智能体", "推荐系统", "知识图谱"]}
        else:
            label = "演示馆内活动"
            values = {"event": "智慧图书馆主题展", "topic": "多智能体与知识图谱"}
        self._cached = ContextObservation(
            source_id=self._source_id,
            kind="EXTERNAL_DEMO",
            label=label,
            status="UP",
            observed_at=now,
            expires_at=now + timedelta(minutes=5),
            values=values,
        )
        return self._cached


def default_external_context_providers() -> tuple[ContextProvider, ...]:
    return tuple(
        LocalDemoExternalContextProvider(source_id)
        for source_id in ("demo-library-schedule", "demo-academic-calendar", "demo-library-events")
    )


def utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "ContextObservation",
    "ContextProvider",
    "LocalDemoExternalContextProvider",
    "default_external_context_providers",
]
