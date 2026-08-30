"""Read-only, consent-gated profile summary adapter for Workspace Agents."""

from __future__ import annotations

from datetime import UTC, datetime
import inspect
from collections.abc import Awaitable, Callable
from typing import Any, Mapping

from backend.app.profile.public import profile_snapshot_reader_from_connection_factory
from backend.app.profile.ports.public import ProfileSnapshotReader


class MySQLWorkspaceProfileReader:
    """Expose only a bounded profile summary through the profile public port."""

    def __init__(
        self,
        reader: ProfileSnapshotReader | Callable[[], Awaitable[Any]],
    ) -> None:
        # Keep the pre-v2 connection-factory call shape as a compatibility
        # seam while the normal composition path injects the public reader
        # port directly.  Both forms retain rollback-only, read-only behavior.
        self._reader = (
            reader
            if hasattr(reader, "get_snapshot")
            else profile_snapshot_reader_from_connection_factory(reader)
        )

    async def close(self) -> None:
        """Close the explicitly composed profile reader, if it owns a pool."""

        close = getattr(self._reader, "close", None)
        if not callable(close):
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    def runtime_metrics(self) -> dict[str, object] | None:
        snapshot = getattr(self._reader, "runtime_metrics", None)
        if not callable(snapshot):
            return None
        value = snapshot()
        return dict(value) if isinstance(value, dict) else None

    async def summary(self, user_id: int) -> Mapping[str, object]:
        if user_id < 10_000:
            raise ValueError("workspace profile reads require a formal account")
        snapshot = await self._reader.get_snapshot(
            user_id=user_id,
            as_of=datetime.now(UTC),
        )
        return {
            "profile_version": f"{snapshot.formula_version}:{snapshot.input_hash[:12]}",
            "event_count": min(snapshot.event_count, 1_000_000),
            "confidence": max(0.0, min(1.0, snapshot.profile_confidence)),
            "interest_count": min(len(snapshot.interests), 100),
            "negative_count": min(len(snapshot.negatives), 100),
            # Only the version and derived signal count are exposed to the
            # global Agent workspace; declared profile text remains in the
            # identity/profile boundary.
            "declared_profile_version": snapshot.declared_profile_version,
            "declared_signal_count": min(len(snapshot.declared_signals), 100),
        }


__all__ = ["MySQLWorkspaceProfileReader"]
