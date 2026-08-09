"""Public ports for recommendation orchestration."""

from __future__ import annotations

from typing import Protocol

from backend.app.recommendation.domain.public import (
    RecommendationTaskCommand,
    RecommendationTaskResult,
)


class RecommendationTaskService(Protocol):
    """Port used by HTTP/worker adapters; implementations own persistence."""

    async def create_task(
        self,
        command: RecommendationTaskCommand,
        *,
        idempotency_key: str,
    ) -> RecommendationTaskResult:
        """Create or replay one task without destructive operations."""
