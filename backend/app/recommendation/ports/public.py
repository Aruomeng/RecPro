"""Public ports for recommendation orchestration."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from backend.app.recommendation.domain.public import (
    RecommendationTaskCommand,
    RecommendationTaskResult,
)
from backend.app.shared_kernel.contracts.auth import AuthenticatedPrincipal


class IdempotencyConflictError(ValueError):
    """The same request identity was reused with a different command payload."""


class StaleContextVersionError(ValueError):
    """A clarification answer targeted an old immutable context version."""


class TaskStateConflictError(ValueError):
    """A command is not valid for the task's current state."""


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

    async def submit_clarification(
        self,
        task_id: UUID,
        *,
        context_version: int,
        answers: dict[str, str],
        idempotency_key: str,
        user_id: int,
    ) -> RecommendationTaskResult:
        """Append answers and continue a task from WAITING_CLARIFICATION."""

    async def get_debug_context(
        self,
        task_id: UUID,
        *,
        actor: AuthenticatedPrincipal,
    ) -> dict[str, Any]:
        """Read sanitized versioned context for a research-admin actor."""

    async def get_debug_policy_decision(
        self,
        task_id: UUID,
        *,
        actor: AuthenticatedPrincipal,
    ) -> dict[str, Any]:
        """Read persisted policy decisions without rerunning policy."""

    async def get_debug_trace(
        self,
        task_id: UUID,
        *,
        actor: AuthenticatedPrincipal,
    ) -> dict[str, Any]:
        """Read a trace for a verified research-admin actor."""
