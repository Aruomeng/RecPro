"""Generic read-only readiness adapter for explicitly composed capabilities."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from backend.app.observability.domain import ComponentReadiness, ComponentStatus


@dataclass(frozen=True, slots=True)
class AsyncOperationReadinessProbe:
    """Run one bounded read operation and expose only sanitized readiness data."""

    operation: Callable[[], Awaitable[object]]
    required: bool
    active_version: str
    error_code: str

    async def check(self) -> ComponentReadiness:
        try:
            await self.operation()
            return ComponentReadiness(
                status=ComponentStatus.UP,
                required=self.required,
                active_version=self.active_version,
            )
        except Exception:
            return ComponentReadiness(
                status=ComponentStatus.DOWN,
                required=self.required,
                active_version=self.active_version,
                error_code=self.error_code,
            )


__all__ = ["AsyncOperationReadinessProbe"]
