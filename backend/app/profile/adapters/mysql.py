"""Read-only MySQL profile projection adapter for G4 composition roots."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.app.profile.ports.public import ProfileSnapshotReader
from backend.app.profile.replay import (
    BehaviorForReplay,
    ProfileSnapshot,
    ResourceTagEvidence,
    compute_profile_snapshot,
)


def _db_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _aware_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("stored behavior event occurred_at is invalid")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class MySQLProfileSnapshotReader(ProfileSnapshotReader):
    """Recompute the deterministic profile snapshot for the requested as-of time."""

    def __init__(self, connection: Any, *, formula_version: str = "profile-g2-v1") -> None:
        self._connection = connection
        self._formula_version = formula_version

    async def get_snapshot(self, *, user_id: int, as_of: datetime) -> ProfileSnapshot:
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                "SELECT id, event_uuid, event_type, resource_id, occurred_at, reason_code "
                "FROM user_behavior_event WHERE user_id = %s AND occurred_at <= %s "
                "ORDER BY occurred_at, id, event_uuid",
                (user_id, _db_datetime(as_of)),
            )
            rows = await cursor.fetchall()
            resource_ids = tuple(sorted({int(row[3]) for row in rows if row[3] is not None}))
            tag_map: dict[int, list[ResourceTagEvidence]] = {resource_id: [] for resource_id in resource_ids}
            if resource_ids:
                placeholders = ",".join("%s" for _ in resource_ids)
                await cursor.execute(
                    "SELECT resource_id, tag_id, weight, confidence FROM resource_tag "
                    f"WHERE resource_id IN ({placeholders}) ORDER BY resource_id, tag_id, source",
                    resource_ids,
                )
                for resource_id, tag_id, weight, confidence in await cursor.fetchall():
                    tag_map[int(resource_id)].append(
                        ResourceTagEvidence(int(tag_id), float(weight), float(confidence))
                    )
        events = tuple(
            BehaviorForReplay(
                event_id=int(row[0]),
                event_uuid=str(row[1]),
                event_type=str(row[2]),
                resource_id=int(row[3]) if row[3] is not None else None,
                occurred_at=_aware_utc(row[4]),
                reason_code=str(row[5]) if row[5] is not None else None,
                tags=tuple(tag_map.get(int(row[3]), ())) if row[3] is not None else (),
            )
            for row in rows
        )
        return compute_profile_snapshot(
            user_id=user_id,
            as_of=as_of,
            events=events,
            formula_version=self._formula_version,
        )


__all__ = ["MySQLProfileSnapshotReader"]
