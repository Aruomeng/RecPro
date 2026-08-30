"""Read-only MySQL profile projection adapter for G4 composition roots."""

from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any
import unicodedata

import asyncmy

from backend.app.profile.ports.public import ProfileSnapshotReader
from backend.app.profile.replay import (
    BehaviorForReplay,
    DeclaredProfileForReplay,
    InterestSignal,
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
            declared_profile = await _read_declared_profile(
                cursor, user_id=user_id, as_of=as_of,
            )
            declared_signals = await _read_declared_signals(
                cursor, declared_profile=declared_profile,
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
            declared_profile=declared_profile,
            declared_signals=declared_signals,
        )


async def _read_declared_profile(
    cursor: Any, *, user_id: int, as_of: datetime,
) -> DeclaredProfileForReplay | None:
    """Read the latest declared profile version visible at ``as_of``.

    The history table is authoritative for replay.  The compatibility
    projection is only a fallback for installations that predate the history
    rows; it is still bounded by its update timestamp.  Missing optional
    tables keep the existing behavior-only profile path usable during a
    rolling deployment, while real connection/query failures still surface.
    """

    timestamp = _db_datetime(as_of)
    try:
        await cursor.execute(
            "SELECT declared_version, major, grade, research_direction, "
            "preferred_language, personalization_enabled, valid_from "
            "FROM user_declared_profile_history "
            "WHERE user_id = %s AND valid_from <= %s "
            "ORDER BY declared_version DESC LIMIT 1",
            (user_id, timestamp),
        )
        row = await _fetchone_compat(cursor)
    except asyncmy.errors.ProgrammingError as exc:
        if "doesn't exist" not in str(exc).lower() and "unknown table" not in str(exc).lower():
            raise
        row = None
    if row is not None:
        return _declared_profile_row(row, timestamp_index=6)

    try:
        await cursor.execute(
            "SELECT declared_version, major, grade, research_direction, "
            "preferred_language, personalization_enabled, updated_at "
            "FROM user_declared_profile WHERE user_id = %s AND updated_at <= %s",
            (user_id, timestamp),
        )
        row = await _fetchone_compat(cursor)
    except asyncmy.errors.ProgrammingError as exc:
        if "doesn't exist" not in str(exc).lower() and "unknown table" not in str(exc).lower():
            raise
        return None
    return _declared_profile_row(row, timestamp_index=6) if row is not None else None


def _declared_profile_row(row: Any, *, timestamp_index: int) -> DeclaredProfileForReplay:
    updated_at = _aware_utc(row[timestamp_index])
    return DeclaredProfileForReplay(
        declared_version=int(row[0]),
        major=_clean_profile_value(row[1]),
        grade=_clean_profile_value(row[2]),
        research_direction=_clean_profile_value(row[3]),
        preferred_language=_clean_profile_value(row[4]),
        personalization_enabled=bool(row[5]),
        updated_at=updated_at,
    )


async def _fetchone_compat(cursor: Any) -> Any:
    """Read one row while keeping lightweight cursor fakes compatible."""

    fetchone = getattr(cursor, "fetchone", None)
    if callable(fetchone):
        return await fetchone()
    rows = await cursor.fetchall()
    return rows[0] if rows else None


def _clean_profile_value(value: object) -> str | None:
    if value is None:
        return None
    clean = unicodedata.normalize("NFKC", str(value)).strip()
    return clean or None


def _declared_terms(profile: DeclaredProfileForReplay) -> tuple[str, ...]:
    """Extract stable, bounded terms without sending raw profile text onward."""

    values = (
        profile.major,
        profile.grade,
        profile.research_direction,
        profile.preferred_language,
    )
    terms: set[str] = set()
    for value in values:
        if not value:
            continue
        normalized = unicodedata.normalize("NFKC", value).casefold()
        for part in re.findall(r"[a-z0-9]{2,64}|[\u4e00-\u9fff]{2,64}", normalized):
            terms.add(part)
            if all("\u4e00" <= char <= "\u9fff" for char in part) and len(part) <= 32:
                for size in (2, 3, 4):
                    terms.update(part[index:index + size] for index in range(max(0, len(part) - size + 1)))
    return tuple(sorted((term for term in terms if len(term) >= 2), key=lambda item: (-len(item), item))[:32])


async def _read_declared_signals(
    cursor: Any, *, declared_profile: DeclaredProfileForReplay | None,
) -> tuple[InterestSignal, ...]:
    if declared_profile is None or not declared_profile.personalization_enabled:
        return ()
    terms = _declared_terms(declared_profile)
    if not terms:
        return ()
    clauses: list[str] = []
    parameters: list[object] = []
    # ``normalized_name`` in the catalog is an opaque, deterministic key
    # (kind + hash), so declared human terms must be matched against the
    # bounded display ``name`` column.  The SQL shape remains fixed and every
    # term is still bound as a parameter; no profile text is interpolated.
    for term in terms:
        clauses.extend(("LOWER(name) = LOWER(%s)", "LOWER(name) LIKE LOWER(%s)"))
        parameters.extend((term, f"%{term}%"))
    query = (
        "SELECT id, name FROM tag_dictionary "
        "WHERE status = 'ACTIVE' AND (" + " OR ".join(clauses) + ") "
        "ORDER BY id LIMIT 64"
    )
    try:
        await cursor.execute(query, tuple(parameters))
        rows = await cursor.fetchall()
    except asyncmy.errors.ProgrammingError as exc:
        if "doesn't exist" not in str(exc).lower() and "unknown table" not in str(exc).lower():
            raise
        return ()
    signals: list[InterestSignal] = []
    for tag_id, tag_name in rows:
        name = _clean_profile_value(tag_name)
        if not name:
            continue
        exact = name.casefold() in terms
        signals.append(
            InterestSignal(
                tag_id=int(tag_id),
                raw_signal=0.9 if exact else 0.6,
                weight=0.85 if exact else 0.65,
                source_count=1,
                last_event_at=declared_profile.updated_at,
            )
        )
    # A tag may match several n-grams; retain one deterministic strongest row.
    strongest: dict[int, InterestSignal] = {}
    for signal in signals:
        prior = strongest.get(signal.tag_id)
        if prior is None or (signal.weight, -signal.tag_id) > (prior.weight, -prior.tag_id):
            strongest[signal.tag_id] = signal
    return tuple(sorted(strongest.values(), key=lambda signal: (signal.tag_id, -signal.weight)))


__all__ = ["MySQLProfileSnapshotReader"]
