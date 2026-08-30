"""Bounded, opt-in worker for append-only Workspace audit facts."""

from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import Any, Awaitable, Callable
from uuid import UUID

from backend.app.agent_workspace.audit import AgentWorkspaceAuditBuffer, DirectiveStateFact, WorkspaceEventFact
from backend.app.agent_workspace.ports.audit import AgentWorkspaceAuditPort


ConnectionFactory = Callable[[], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class AuditDrainReport:
    attempted: int
    appended: int
    remaining: int
    error: str | None = None


class AgentWorkspaceAuditWorker:
    def __init__(
        self,
        *,
        buffer: AgentWorkspaceAuditBuffer,
        adapter: AgentWorkspaceAuditPort,
        connection_factory: ConnectionFactory,
        max_batch: int = 32,
    ) -> None:
        if not 1 <= max_batch <= 64:
            raise ValueError("audit max_batch must be between 1 and 64")
        self._buffer = buffer
        self._adapter = adapter
        self._connection_factory = connection_factory
        self._max_batch = max_batch

    async def close(self) -> None:
        """Close the explicitly supplied pool without draining or deleting facts."""

        close = getattr(self._connection_factory, "close", None)
        if not callable(close):
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    async def drain_once(self) -> AuditDrainReport:
        batch = self._buffer.snapshot()[: self._max_batch]
        if not batch:
            return AuditDrainReport(0, 0, 0)
        connection = await self._connection_factory()
        acknowledged: set[UUID] = set()
        try:
            for fact in batch:
                await self._adapter.append(connection, fact)
                acknowledged.add(fact.event_uuid if isinstance(fact, WorkspaceEventFact) else fact.fact_uuid)
            await connection.commit()
        except Exception as exc:
            await connection.rollback()
            return AuditDrainReport(len(batch), 0, self._buffer.pending_count, type(exc).__name__)
        finally:
            close = getattr(connection, "close", None)
            if callable(close):
                close()
        self._buffer.acknowledge(acknowledged)
        return AuditDrainReport(len(batch), len(acknowledged), self._buffer.pending_count)


__all__ = ["AgentWorkspaceAuditWorker", "AuditDrainReport"]
