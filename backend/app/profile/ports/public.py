"""Read-only profile snapshot boundary for recommendation orchestration."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from backend.app.feedback.domain.public import (
    BehaviorAppendCommand,
    BehaviorReceipt,
    ProfileRefreshReceipt,
)
from backend.app.profile.replay import ProfileSnapshot


class ProfileSnapshotReader(Protocol):
    """Return a deterministic profile projection without changing profile facts."""

    async def get_snapshot(self, *, user_id: int, as_of: datetime) -> ProfileSnapshot:
        """Read the projection appropriate for the requested evaluation time."""


class BehaviorAppendPort(Protocol):
    """Append one immutable behavior fact and, when needed, its profile outbox."""

    async def append_behavior(
        self,
        connection: object,
        command: BehaviorAppendCommand,
    ) -> BehaviorReceipt: ...


class ProfileRefreshPort(Protocol):
    """Claim and apply profile outbox work using caller-owned connections."""

    async def claim_pending(
        self,
        connection: object,
        *,
        worker_id: str,
        limit: int,
        lease_seconds: int,
        max_attempts: int,
    ) -> tuple[dict[str, object], ...]: ...

    async def apply_claim(
        self,
        connection: object,
        work: dict[str, object],
        *,
        formula_version: str,
    ) -> ProfileRefreshReceipt: ...

    async def mark_done(self, connection: object, *, outbox_id: int) -> None: ...

    async def mark_failed(
        self,
        connection: object,
        *,
        outbox_id: int,
        error_code: str,
        dead: bool,
    ) -> None: ...


__all__ = ["BehaviorAppendPort", "ProfileRefreshPort", "ProfileSnapshotReader"]
