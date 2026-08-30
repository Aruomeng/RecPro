"""Read-only, consent-gated profile summary adapter for Workspace Agents."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Mapping

from backend.app.profile.ports.public import ProfileSnapshotReader


class MySQLWorkspaceProfileReader:
    """Expose only a bounded profile summary through the profile public port."""

    def __init__(self, reader: ProfileSnapshotReader) -> None:
        self._reader = reader

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
