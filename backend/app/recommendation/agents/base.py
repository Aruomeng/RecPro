"""Framework-independent Agent boundary for the G4 in-process orchestrator."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Awaitable, Callable, Protocol, TypeVar

from backend.app.shared_kernel.contracts.agent import AgentMessage, AgentResult


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded, no-backoff retry policy for read-only Agent dependencies."""

    max_attempts: int = 2

    def __post_init__(self) -> None:
        if isinstance(self.max_attempts, bool) or not 1 <= self.max_attempts <= 3:
            raise ValueError("max_attempts must be between 1 and 3")


class DependencyCallFailed(TimeoutError):
    """A dependency exhausted its bounded retry budget or deadline."""

    def __init__(self, operation: str, *, attempts: int, timed_out: bool = False) -> None:
        self.operation = operation
        self.attempts = attempts
        self.timed_out = timed_out
        reason = "deadline" if timed_out else "retry budget"
        super().__init__(f"{operation} failed after {attempts} attempt(s): {reason}")


T = TypeVar("T")


async def call_with_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    operation_name: str,
    deadline_at: datetime,
    policy: RetryPolicy,
) -> tuple[T, int]:
    """Run a dependency call with deadline-aware, bounded retries."""

    attempts = 0
    while attempts < policy.max_attempts:
        now = datetime.now(UTC)
        remaining = (deadline_at - now).total_seconds()
        if remaining <= 0:
            raise DependencyCallFailed(operation_name, attempts=attempts, timed_out=True)
        attempts += 1
        try:
            return await asyncio.wait_for(operation(), timeout=remaining), attempts
        except asyncio.CancelledError:
            raise
        except (TimeoutError, ConnectionError, OSError) as exc:
            if attempts >= policy.max_attempts:
                timed_out = isinstance(exc, TimeoutError)
                raise DependencyCallFailed(
                    operation_name, attempts=attempts, timed_out=timed_out
                ) from exc
    raise DependencyCallFailed(operation_name, attempts=attempts)


class Agent(Protocol):
    """One addressable capability; Agents never call one another directly."""

    @property
    def name(self) -> str:
        ...

    @property
    def version(self) -> str:
        ...

    async def handle(self, message: AgentMessage) -> AgentResult[dict[str, object]]:
        """Handle one validated message and return a structured result."""


__all__ = ["Agent", "DependencyCallFailed", "RetryPolicy", "call_with_retry"]
