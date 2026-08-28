"""Bounded FIFO dispatcher: one observation at a time per Workspace."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Awaitable, Callable

from backend.app.agent_workspace.ports.handlers import WorkspaceObservation


class WorkspaceObservationCapacityError(RuntimeError):
    pass


Processor = Callable[[WorkspaceObservation], Awaitable[None]]
FailureHandler = Callable[[WorkspaceObservation, Exception], None]


@dataclass(slots=True)
class _Lane:
    queue: deque[WorkspaceObservation]
    task: asyncio.Task[None] | None = None


class WorkspaceObservationDispatcher:
    def __init__(
        self,
        *,
        processor: Processor,
        failure_handler: FailureHandler | None = None,
        max_concurrent: int = 16,
        max_pending: int = 64,
    ) -> None:
        if not 1 <= max_concurrent <= 16 or not 1 <= max_pending <= 64:
            raise ValueError("workspace dispatcher bounds exceed the contract")
        self._processor = processor
        self._failure_handler = failure_handler
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_pending = max_pending
        self._pending = 0
        self._lanes: dict[str, _Lane] = {}
        self._idle = asyncio.Event()
        self._idle.set()

    @property
    def pending_count(self) -> int:
        return self._pending

    def submit(self, observation: WorkspaceObservation) -> None:
        if self._pending >= self._max_pending:
            raise WorkspaceObservationCapacityError(
                "workspace observation queue capacity reached"
            )
        try:
            asyncio.get_running_loop()
        except RuntimeError as exc:
            raise RuntimeError("workspace observation submission requires an event loop") from exc
        key = str(observation.workspace_id)
        lane = self._lanes.setdefault(key, _Lane(deque()))
        lane.queue.append(observation)
        self._pending += 1
        self._idle.clear()
        if lane.task is None or lane.task.done():
            lane.task = asyncio.create_task(self._drain(key, lane), name=f"workspace-observations:{key}")

    async def wait_idle(self) -> None:
        await self._idle.wait()

    async def _drain(self, key: str, lane: _Lane) -> None:
        try:
            while lane.queue:
                observation = lane.queue.popleft()
                try:
                    async with self._semaphore:
                        try:
                            await self._processor(observation)
                        except Exception as exc:
                            if self._failure_handler is not None:
                                self._failure_handler(observation, exc)
                finally:
                    self._pending -= 1
                    if self._pending == 0:
                        self._idle.set()
        finally:
            self._lanes.pop(key, None)


__all__ = ["WorkspaceObservationCapacityError", "WorkspaceObservationDispatcher"]
