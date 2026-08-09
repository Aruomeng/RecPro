"""Public ports for recommendation orchestration."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from backend.app.recommendation.domain.public import (
    RecommendationTaskCommand,
    RecommendationTaskResult,
)


class IdempotencyConflictError(ValueError):
    """The same request identity was reused with a different command payload."""


class RecommendationTaskService(Protocol):
    """Port used by HTTP/worker adapters; implementations own persistence."""

    async def create_task(
        self,
        command: RecommendationTaskCommand,
        *,
        idempotency_key: str,
    ) -> RecommendationTaskResult:
        """Create or replay one task without destructive operations."""

    async def get_task(
        self,
        task_id: UUID,
        *,
        user_id: int,
    ) -> dict[str, Any]:
        """Read task state without progressing or rewriting it."""

    async def get_trace(
        self,
        task_id: UUID,
        *,
        user_id: int,
    ) -> dict[str, Any]:
        """Read the persisted ordered trace without recomputation."""
