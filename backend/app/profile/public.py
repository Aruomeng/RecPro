"""Public profile construction seam used by adjacent bounded contexts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from backend.app.profile.adapters.factory import MySQLProfileSnapshotReaderFactory
from backend.app.profile.ports.public import ProfileSnapshotReader


ConnectionFactory = Callable[[], Awaitable[Any]]


def profile_snapshot_reader_from_connection_factory(
    connection_factory: ConnectionFactory,
) -> ProfileSnapshotReader:
    """Adapt the legacy connection-factory call shape to the public port."""

    return MySQLProfileSnapshotReaderFactory(connection_factory)


__all__ = ["profile_snapshot_reader_from_connection_factory"]
