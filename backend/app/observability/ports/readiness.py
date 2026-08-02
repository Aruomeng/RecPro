"""Outbound readiness probe contract."""

from __future__ import annotations

from typing import Protocol

from backend.app.observability.domain import ComponentReadiness


class ReadinessProbe(Protocol):
    async def check(self) -> ComponentReadiness:
        """Return a sanitized component result without raising dependency errors."""

        ...
