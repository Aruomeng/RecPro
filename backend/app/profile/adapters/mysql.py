"""Read-only MySQL profile projection adapter for G4 composition roots."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from backend.app.profile.ports.public import ProfileSnapshotReader
from backend.app.profile.replay import InterestSignal, NegativeSignal, ProfileSnapshot


def _empty_hash(*, user_id: int, as_of: datetime, formula_version: str) -> str:
    payload = {
        "user_id": user_id,
        "as_of": as_of.isoformat(),
        "formula_version": formula_version,
        "events": [],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _db_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _utc_datetime(value: object, fallback: datetime) -> datetime:
    if not isinstance(value, datetime):
        return fallback
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class MySQLProfileSnapshotReader(ProfileSnapshotReader):
    """Read the current, versioned profile projection using SELECT only."""

    def __init__(self, connection: Any, *, formula_version: str = "profile-g2-v1") -> None:
        self._connection = connection
        self._formula_version = formula_version

    async def get_snapshot(self, *, user_id: int, as_of: datetime) -> ProfileSnapshot:
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                "SELECT profile_version, profile_confidence, recent_focus_tag_id, "
                "topic_focus_strength FROM user_profile WHERE user_id = %s",
                (user_id,),
            )
            profile = await cursor.fetchone()
            await cursor.execute(
                "SELECT tag_id, raw_positive_signal, positive_weight, source_count, last_event_at "
                "FROM user_interest_tag WHERE user_id = %s AND positive_weight > 0 ORDER BY tag_id",
                (user_id,),
            )
            interests = await cursor.fetchall()
            await cursor.execute(
                "SELECT tag_id, reason_code, raw_negative_signal, negative_weight, source_count, last_event_at "
                "FROM user_negative_preference WHERE user_id = %s AND negative_weight > 0 "
                "ORDER BY tag_id, reason_code",
                (user_id,),
            )
            negatives = await cursor.fetchall()
            await cursor.execute(
                "SELECT as_of, formula_version, input_hash, event_count "
                "FROM profile_replay_run WHERE user_id = %s AND as_of <= %s "
                "ORDER BY as_of DESC, profile_version DESC LIMIT 1",
                (user_id, _db_datetime(as_of)),
            )
            replay = await cursor.fetchone()
        if profile is None:
            return ProfileSnapshot(
                user_id=user_id,
                as_of=as_of,
                formula_version=self._formula_version,
                event_count=0,
                profile_confidence=0.0,
                recent_focus_tag_id=None,
                topic_focus_strength=0.0,
                interests=(),
                negatives=(),
                input_hash=_empty_hash(
                    user_id=user_id, as_of=as_of, formula_version=self._formula_version
                ),
            )
        replay_as_of = replay[0] if replay is not None else None
        replay_formula = str(replay[1]) if replay is not None and replay[1] else self._formula_version
        input_hash = str(replay[2]) if replay is not None and replay[2] else _empty_hash(
            user_id=user_id, as_of=as_of, formula_version=replay_formula
        )
        event_count = int(replay[3]) if replay is not None and replay[3] is not None else 0
        return ProfileSnapshot(
            user_id=user_id,
            as_of=_utc_datetime(replay_as_of, as_of),
            formula_version=replay_formula,
            event_count=event_count,
            profile_confidence=float(profile[1]),
            recent_focus_tag_id=int(profile[2]) if profile[2] is not None else None,
            topic_focus_strength=float(profile[3]),
            interests=tuple(
                InterestSignal(
                    tag_id=int(row[0]),
                    raw_signal=float(row[1]),
                    weight=float(row[2]),
                    source_count=int(row[3]),
                    last_event_at=row[4],
                )
                for row in interests
            ),
            negatives=tuple(
                NegativeSignal(
                    tag_id=int(row[0]),
                    reason_code=str(row[1]),
                    raw_signal=float(row[2]),
                    weight=float(row[3]),
                    source_count=int(row[4]),
                    last_event_at=row[5],
                )
                for row in negatives
            ),
            input_hash=input_hash,
        )


__all__ = ["MySQLProfileSnapshotReader"]
