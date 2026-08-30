"""Bounded in-memory progress broker for the explicit research kiosk."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
import time
from typing import AsyncIterator
from uuid import UUID

from backend.app.recommendation.application.public import (
    RunCapacityError,
    RunContextConflictError,
    RunIdempotencyConflictError,
    RunNotFoundError,
)


@dataclass(slots=True)
class _Run:
    task_id: UUID
    trace_id: UUID
    context_version: int
    user_id: int
    created_at: float
    request_fingerprint: str
    events: deque[dict[str, object]] = field(default_factory=lambda: deque(maxlen=256))
    subscribers: set[asyncio.Queue[dict[str, object]]] = field(default_factory=set)
    terminal: bool = False
    status: str = "ACCEPTED"
    result: dict[str, object] | None = None
    error_code: str | None = None
    finished_at: float | None = None
    task: asyncio.Task[None] | None = None


class ScopedProgressSink:
    def __init__(self, broker: "RecommendationProgressBroker", task_id: UUID) -> None:
        self._broker = broker
        self._task_id = task_id

    def publish(self, event_type: str, payload: dict[str, object]) -> None:
        self._broker.publish(self._task_id, event_type, payload)


class RecommendationProgressBroker:
    def __init__(self, *, max_concurrent: int = 8, retention_seconds: float = 600.0) -> None:
        self._max_concurrent = max_concurrent
        self._retention_seconds = retention_seconds
        self._runs: dict[UUID, _Run] = {}
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    async def close(self) -> None:
        """Wait for accepted runs before the owning HTTP app shuts down."""

        if self._closed:
            return
        self._closed = True
        tasks = tuple(
            run.task for run in self._runs.values()
            if run.task is not None and not run.task.done()
        )
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def reserve(self, *, task_id: UUID, trace_id: UUID, context_version: int, user_id: int, request_fingerprint: str) -> tuple[ScopedProgressSink, bool]:
        if self._closed:
            raise RuntimeError("recommendation progress broker is closed")
        if not request_fingerprint.strip():
            raise ValueError("request fingerprint must not be blank")
        self._prune()
        existing = self._runs.get(task_id)
        if existing is not None:
            if existing.user_id != user_id:
                raise RunNotFoundError("run is not visible to this user")
            if existing.context_version == context_version:
                if existing.request_fingerprint != request_fingerprint:
                    raise RunIdempotencyConflictError("run identity was reused with a different payload")
                return ScopedProgressSink(self, task_id), True
            if not existing.terminal or context_version <= existing.context_version:
                raise RunContextConflictError("a different context for this task is still active")
        active = sum(not run.terminal for run in self._runs.values())
        if active >= self._max_concurrent:
            raise RunCapacityError("recommendation run capacity reached")
        self._runs[task_id] = _Run(task_id, trace_id, context_version, user_id, time.monotonic(), request_fingerprint)
        sink = ScopedProgressSink(self, task_id)
        sink.publish("TASK_ACCEPTED", {"status": "ACCEPTED", "context_version": context_version})
        return sink, False

    def attach_task(self, task_id: UUID, task: asyncio.Task[None]) -> None:
        self._required(task_id).task = task

    def publish(self, task_id: UUID, event_type: str, payload: dict[str, object]) -> dict[str, object]:
        run = self._required(task_id)
        event = {
            "schema_version": "agent-progress-v1",
            "sequence": (int(run.events[-1]["sequence"]) + 1) if run.events else 1,
            "event_type": event_type,
            "task_id": str(run.task_id),
            "trace_id": str(run.trace_id),
            "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            **payload,
        }
        run.events.append(event)
        if isinstance(payload.get("status"), str):
            run.status = str(payload["status"])
        for queue in tuple(run.subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                run.subscribers.discard(queue)
        return event

    def complete(self, task_id: UUID, *, result: dict[str, object], replayed: bool) -> None:
        run = self._required(task_id)
        run.result = result
        run.terminal = True
        run.status = str(result.get("status", "COMPLETED"))
        run.finished_at = time.monotonic()
        self.publish(task_id, "TASK_COMPLETED", {"status": run.status, "replayed": replayed, "context_version": run.context_version})

    def fail(self, task_id: UUID, *, error_code: str) -> None:
        run = self._required(task_id)
        run.terminal = True
        run.status = "FAILED"
        run.error_code = error_code
        run.finished_at = time.monotonic()
        self.publish(task_id, "TASK_FAILED", {"status": "FAILED", "error_code": error_code, "context_version": run.context_version})

    def state(self, task_id: UUID, *, user_id: int) -> dict[str, object]:
        run = self._visible(task_id, user_id)
        return {
            "task_id": str(run.task_id), "trace_id": str(run.trace_id), "context_version": run.context_version,
            "status": run.status, "terminal": run.terminal, "error_code": run.error_code, "result": run.result,
        }

    async def events(self, task_id: UUID, *, user_id: int, after_sequence: int = 0) -> AsyncIterator[dict[str, object] | None]:
        run = self._visible(task_id, user_id)
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=256)
        for event in run.events:
            if int(event["sequence"]) > after_sequence:
                queue.put_nowait(event)
        run.subscribers.add(queue)
        try:
            while True:
                if run.terminal and queue.empty():
                    break
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield None
        finally:
            run.subscribers.discard(queue)

    def _visible(self, task_id: UUID, user_id: int) -> _Run:
        self._prune()
        run = self._required(task_id)
        if run.user_id != user_id:
            raise RunNotFoundError("run is not visible to this user")
        return run

    def _required(self, task_id: UUID) -> _Run:
        try:
            return self._runs[task_id]
        except KeyError as exc:
            raise RunNotFoundError("recommendation run not found") from exc

    def _prune(self) -> None:
        now = time.monotonic()
        stale = [task_id for task_id, run in self._runs.items() if run.terminal and run.finished_at is not None and now - run.finished_at > self._retention_seconds]
        for task_id in stale:
            self._runs.pop(task_id, None)


__all__ = ["RecommendationProgressBroker", "RunCapacityError", "RunContextConflictError", "RunIdempotencyConflictError", "RunNotFoundError", "ScopedProgressSink"]
