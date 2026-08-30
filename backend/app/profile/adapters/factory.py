"""Connection-factory adapter for the public profile snapshot port."""

from __future__ import annotations

from datetime import datetime
import inspect
from typing import Any, Awaitable, Callable

from backend.app.profile.adapters.mysql import MySQLProfileSnapshotReader
from backend.app.profile.ports.public import ProfileSnapshotReader


ConnectionFactory = Callable[[], Awaitable[Any]]


class MySQLProfileSnapshotReaderFactory(ProfileSnapshotReader):
    """Open a short-lived read-only connection for a profile snapshot."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        formula_version: str = "profile-g2-v1",
    ) -> None:
        self._connection_factory = connection_factory
        self._formula_version = formula_version

    async def close(self) -> None:
        """Close an explicitly composed pool used for profile reads."""

        close = getattr(self._connection_factory, "close", None)
        if not callable(close):
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    def runtime_metrics(self) -> dict[str, object] | None:
        snapshot = getattr(self._connection_factory, "snapshot", None)
        if not callable(snapshot):
            return None
        value = snapshot()
        as_dict = getattr(value, "as_dict", None)
        if callable(as_dict):
            value = as_dict()
        return dict(value) if isinstance(value, dict) else None

    async def get_snapshot(self, *, user_id: int, as_of: datetime):
        connection = await self._connection_factory()
        try:
            return await MySQLProfileSnapshotReader(
                connection,
                formula_version=self._formula_version,
            ).get_snapshot(user_id=user_id, as_of=as_of)
        finally:
            rollback = getattr(connection, "rollback", None)
            if callable(rollback):
                outcome = rollback()
                if inspect.isawaitable(outcome):
                    await outcome
            close = getattr(connection, "close", None)
            if callable(close):
                close()


__all__ = ["MySQLProfileSnapshotReaderFactory"]
