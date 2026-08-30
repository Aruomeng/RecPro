"""Lazy, bounded async MySQL connection pooling.

The application ports expect a callable that returns one connection with
``cursor``, ``commit``, ``rollback`` and ``close`` methods.  ``asyncmy``
normally exposes a pool lease through ``Pool.release``; calling
``connection.close`` on the raw leased connection would physically close it
instead of returning it to the pool.  This module keeps that lifecycle detail
inside the platform adapter and leaves business services unchanged.
"""

from __future__ import annotations

import asyncio
import inspect
import math
from collections.abc import Mapping
from dataclasses import dataclass
import time
from typing import Any

import asyncmy


async def _await_if_needed(value: object) -> None:
    if inspect.isawaitable(value):
        await value


@dataclass(frozen=True, slots=True)
class MySQLPoolSnapshot:
    """Non-sensitive pool state suitable for diagnostics and acceptance logs."""

    initialized: bool
    closed: bool
    min_size: int
    max_size: int
    recycle_seconds: int
    acquire_timeout_seconds: float
    pool_size: int
    free_size: int
    active_leases: int
    pending_acquires: int
    acquire_count: int
    acquire_timeout_count: int
    release_count: int
    total_acquire_ms: float
    last_acquire_ms: float | None
    average_acquire_ms: float | None

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-shaped copy without connection options or secrets."""

        return {
            "initialized": self.initialized,
            "closed": self.closed,
            "min_size": self.min_size,
            "max_size": self.max_size,
            "recycle_seconds": self.recycle_seconds,
            "acquire_timeout_seconds": self.acquire_timeout_seconds,
            "pool_size": self.pool_size,
            "free_size": self.free_size,
            "active_leases": self.active_leases,
            "pending_acquires": self.pending_acquires,
            "acquire_count": self.acquire_count,
            "acquire_timeout_count": self.acquire_timeout_count,
            "release_count": self.release_count,
            "total_acquire_ms": self.total_acquire_ms,
            "last_acquire_ms": self.last_acquire_ms,
            "average_acquire_ms": self.average_acquire_ms,
        }


class PooledConnectionLease:
    """Connection-shaped lease whose ``close`` returns it to its pool."""

    __slots__ = ("_connection", "_pool", "_owner", "_released")

    def __init__(self, pool: Any, connection: Any, owner: "MySQLConnectionPool" | None = None) -> None:
        self._pool = pool
        self._owner = owner
        self._connection = connection
        self._released = False

    @property
    def released(self) -> bool:
        return self._released

    def __getattr__(self, name: str) -> Any:
        connection = self._connection
        if connection is None:
            raise RuntimeError("MySQL connection lease has already been released")
        return getattr(connection, name)

    def close(self) -> object:
        """Release this lease exactly once.

        ``Pool.release`` is intentionally called synchronously.  asyncmy may
        return a wake-up Future when another coroutine is waiting for a lease;
        callers that use an async close helper can await that value, while the
        many existing synchronous ``close()`` call sites remain compatible.
        """

        if self._released:
            return None
        self._released = True
        connection = self._connection
        self._connection = None
        if connection is None:
            return None
        try:
            result = self._pool.release(connection)
        except BaseException:
            if self._owner is not None:
                self._owner._record_release()
            raise
        if self._owner is not None:
            self._owner._record_release()
        return result

    async def __aenter__(self) -> "PooledConnectionLease":
        if self._released:
            raise RuntimeError("MySQL connection lease has already been released")
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await _await_if_needed(self.close())


class MySQLConnectionPool:
    """A lazy, bounded connection-factory adapter for asyncmy.

    No socket is opened during construction.  The underlying pool is created
    on the first ``await pool()`` call, and ``min_size=0`` is the safe default.
    Every request acquires one bounded lease and existing application code can
    continue to call ``connection.close()`` without knowing the pool details.
    """

    def __init__(
        self,
        *,
        connection_options: Mapping[str, Any],
        min_size: int = 0,
        max_size: int = 10,
        pool_recycle_seconds: int = 1800,
        acquire_timeout_seconds: float = 3.0,
    ) -> None:
        if isinstance(min_size, bool) or not 0 <= min_size <= 32:
            raise ValueError("MySQL pool min size must be between 0 and 32")
        if isinstance(max_size, bool) or not 1 <= max_size <= 64:
            raise ValueError("MySQL pool max size must be between 1 and 64")
        if min_size > max_size:
            raise ValueError("MySQL pool min size cannot exceed max size")
        if (
            isinstance(pool_recycle_seconds, bool)
            or not 60 <= pool_recycle_seconds <= 86400
        ):
            raise ValueError("MySQL pool recycle must be between 60 and 86400 seconds")
        if (
            isinstance(acquire_timeout_seconds, bool)
            or not math.isfinite(float(acquire_timeout_seconds))
            or not 0.0 < float(acquire_timeout_seconds) <= 30.0
        ):
            raise ValueError("MySQL pool acquire timeout must be between 0 and 30 seconds")
        self._connection_options = dict(connection_options)
        self._min_size = min_size
        self._max_size = max_size
        self._pool_recycle_seconds = pool_recycle_seconds
        self._acquire_timeout_seconds = float(acquire_timeout_seconds)
        self._pool: Any | None = None
        self._initializing = asyncio.Lock()
        self._closed = False
        self._pending_acquires = 0
        self._active_leases = 0
        self._acquire_count = 0
        self._acquire_timeout_count = 0
        self._release_count = 0
        self._total_acquire_ms = 0.0
        self._last_acquire_ms: float | None = None

    async def _ensure_pool(self) -> Any:
        if self._closed:
            raise RuntimeError("MySQL connection pool is closed")
        if self._pool is not None:
            return self._pool
        async with self._initializing:
            if self._closed:
                raise RuntimeError("MySQL connection pool is closed")
            if self._pool is not None:
                return self._pool
            context = asyncmy.create_pool(
                minsize=self._min_size,
                maxsize=self._max_size,
                pool_recycle=self._pool_recycle_seconds,
                **self._connection_options,
            )
            try:
                self._pool = await context
            except BaseException:
                close_context = getattr(context, "close", None)
                if callable(close_context):
                    close_context()
                raise
            return self._pool

    async def __call__(self) -> PooledConnectionLease:
        started = time.perf_counter()
        self._pending_acquires += 1
        try:
            pool = await self._ensure_pool()
            try:
                connection = await asyncio.wait_for(
                    pool.acquire(),
                    timeout=self._acquire_timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                self._acquire_timeout_count += 1
                raise TimeoutError(
                    "MySQL connection pool acquire timed out"
                ) from exc
        finally:
            self._pending_acquires = max(0, self._pending_acquires - 1)
        if self._closed:
            await _await_if_needed(pool.release(connection))
            raise RuntimeError("MySQL connection pool is closed")
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
        self._acquire_count += 1
        self._total_acquire_ms += elapsed_ms
        self._last_acquire_ms = elapsed_ms
        self._active_leases += 1
        return PooledConnectionLease(pool, connection, self)

    def _record_release(self) -> None:
        self._release_count += 1
        self._active_leases = max(0, self._active_leases - 1)

    @staticmethod
    def _pool_int(pool: Any | None, name: str) -> int:
        if pool is None:
            return 0
        try:
            value = getattr(pool, name, 0)
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    def snapshot(self) -> MySQLPoolSnapshot:
        """Return bounded state and acquisition timings for observability."""

        average = (
            round(self._total_acquire_ms / self._acquire_count, 3)
            if self._acquire_count
            else None
        )
        return MySQLPoolSnapshot(
            initialized=self._pool is not None,
            closed=self._closed,
            min_size=self._min_size,
            max_size=self._max_size,
            recycle_seconds=self._pool_recycle_seconds,
            acquire_timeout_seconds=self._acquire_timeout_seconds,
            pool_size=self._pool_int(self._pool, "size"),
            free_size=self._pool_int(self._pool, "freesize"),
            active_leases=self._active_leases,
            pending_acquires=self._pending_acquires,
            acquire_count=self._acquire_count,
            acquire_timeout_count=self._acquire_timeout_count,
            release_count=self._release_count,
            total_acquire_ms=round(self._total_acquire_ms, 3),
            last_acquire_ms=self._last_acquire_ms,
            average_acquire_ms=average,
        )

    async def close(self) -> None:
        """Stop the pool after current leases have returned."""

        async with self._initializing:
            self._closed = True
            pool = self._pool
        if pool is None:
            return
        pool.close()
        await pool.wait_closed()

    async def __aenter__(self) -> "MySQLConnectionPool":
        if self._closed:
            raise RuntimeError("MySQL connection pool is closed")
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.close()


__all__ = ["MySQLConnectionPool", "MySQLPoolSnapshot", "PooledConnectionLease"]
