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
from typing import Any

import asyncmy


async def _await_if_needed(value: object) -> None:
    if inspect.isawaitable(value):
        await value


class PooledConnectionLease:
    """Connection-shaped lease whose ``close`` returns it to its pool."""

    __slots__ = ("_connection", "_pool", "_released")

    def __init__(self, pool: Any, connection: Any) -> None:
        self._pool = pool
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
        return self._pool.release(connection)

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
        pool = await self._ensure_pool()
        try:
            connection = await asyncio.wait_for(
                pool.acquire(),
                timeout=self._acquire_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                "MySQL connection pool acquire timed out"
            ) from exc
        if self._closed:
            await _await_if_needed(pool.release(connection))
            raise RuntimeError("MySQL connection pool is closed")
        return PooledConnectionLease(pool, connection)

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


__all__ = ["MySQLConnectionPool", "PooledConnectionLease"]
