"""Outbound state-transition audit contract."""

from __future__ import annotations

from typing import Protocol

from backend.app.observability.domain.transition import StateTransition


class StateTransitionSink(Protocol):
    """Append one transition using the caller-owned transaction."""

    async def append(self, connection: object, transition: StateTransition) -> None: ...


__all__ = ["StateTransitionSink"]
