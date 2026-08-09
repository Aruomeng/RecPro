"""Read-only profile snapshot boundary for recommendation orchestration."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from backend.app.profile.replay import ProfileSnapshot


class ProfileSnapshotReader(Protocol):
    """Return a deterministic profile projection without changing profile facts."""

    async def get_snapshot(self, *, user_id: int, as_of: datetime) -> ProfileSnapshot:
        """Read the projection appropriate for the requested evaluation time."""


__all__ = ["ProfileSnapshotReader"]
