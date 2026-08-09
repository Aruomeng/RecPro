"""Transactional append-only ports for G4 Agent execution facts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Protocol
from uuid import UUID

from backend.app.shared_kernel.contracts.agent import AgentMessage, AgentResult, ArtifactRef


class AgentExecutionLogPort(Protocol):
    """Write Agent facts using a caller-owned transaction connection."""

    async def append_message(self, connection: Any, message: AgentMessage) -> None:
        """Append or safely replay one immutable Agent message."""

    async def append_result(
        self,
        connection: Any,
        *,
        task_id: UUID,
        trace_id: UUID,
        context_version: int,
        message: AgentMessage,
        result: AgentResult[dict[str, object]],
        created_at: datetime | None = None,
    ) -> None:
        """Append or safely replay the result for one message."""

    async def append_artifact(
        self,
        connection: Any,
        *,
        task_id: UUID,
        trace_id: UUID,
        context_version: int,
        artifact: ArtifactRef,
        metadata: Mapping[str, object] | None = None,
        created_at: datetime | None = None,
    ) -> None:
        """Append or safely replay one content-addressed artifact reference."""

    async def append_orchestration_result(
        self,
        connection: Any,
        *,
        task_id: UUID,
        trace_id: UUID,
        context_version: int,
        schema_version: str,
        status: str,
        replan_count: int,
        payload: Mapping[str, object],
        transitions: tuple[Mapping[str, object], ...],
        trace: tuple[Mapping[str, object], ...],
        created_at: datetime | None = None,
    ) -> None:
        """Append or safely replay the final Orchestrator result."""


__all__ = ["AgentExecutionLogPort"]
