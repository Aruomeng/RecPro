"""MySQL profile outbox claim/apply adapter for the first G5 worker slice."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from backend.app.feedback.domain.public import ProfileRefreshReceipt
from backend.app.profile.ports.public import ProfileRefreshPort
from backend.app.profile.replay import (
    BehaviorForReplay,
    ResourceTagEvidence,
    compute_profile_snapshot,
)


DECIMAL_6 = Decimal("0.000001")


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decimal(value: float | int) -> Decimal:
    return Decimal(str(value)).quantize(DECIMAL_6, rounding=ROUND_HALF_UP)


def _db_datetime(value: datetime) -> datetime:
    if value.tzinfo is not None and value.utcoffset() is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


async def _read_events(connection: Any, *, user_id: int, as_of: datetime) -> tuple[BehaviorForReplay, ...]:
    async with connection.cursor() as cursor:
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
    return tuple(
        BehaviorForReplay(
            event_id=int(row[0]),
            event_uuid=str(row[1]),
            event_type=str(row[2]),
            resource_id=int(row[3]) if row[3] is not None else None,
            occurred_at=row[4],
            reason_code=str(row[5]) if row[5] is not None else None,
            tags=tuple(tag_map.get(int(row[3]), ())) if row[3] is not None else (),
        )
        for row in rows
    )


class MySQLProfileRefreshAdapter(ProfileRefreshPort):
    """Apply one outbox item with versioned, idempotent profile projection writes."""

    async def claim_pending(
        self,
        connection: Any,
        *,
        worker_id: str,
        limit: int,
        lease_seconds: int,
        max_attempts: int,
    ) -> tuple[dict[str, object], ...]:
        if not 1 <= limit <= 100:
            raise ValueError("profile outbox limit must be between 1 and 100")
        if not 1 <= max_attempts <= 10:
            raise ValueError("profile outbox max_attempts must be between 1 and 10")
        now = datetime.now(UTC).replace(tzinfo=None)
        stale_before = now - timedelta(seconds=max(1, lease_seconds))
        claimed: list[dict[str, object]] = []
        async with connection.cursor() as cursor:
            await cursor.execute(
                "UPDATE profile_update_outbox SET status = 'DEAD', last_error = %s, "
                "locked_at = NULL, locked_by = NULL, updated_at = %s "
                "WHERE status IN ('PENDING','PROCESSING') AND attempts >= %s",
                ("MAX_ATTEMPTS", now, max_attempts),
            )
            await cursor.execute(
                "SELECT id, user_id, source_event_id, source_type, payload_json, attempts "
                "FROM profile_update_outbox WHERE "
                "(status = 'PENDING' AND (next_retry_at IS NULL OR next_retry_at <= %s)) "
                "OR (status = 'PROCESSING' AND locked_at <= %s AND attempts < %s) "
                "ORDER BY id LIMIT %s FOR UPDATE",
                (now, stale_before, max_attempts, limit),
            )
            rows = await cursor.fetchall()
            for row in rows:
                await cursor.execute(
                    "UPDATE profile_update_outbox SET status = 'PROCESSING', attempts = attempts + 1, "
                    "locked_at = %s, locked_by = %s, last_error = NULL, updated_at = %s WHERE id = %s",
                    (now, worker_id, now, int(row[0])),
                )
                claimed.append(
                    {
                        "outbox_id": int(row[0]),
                        "user_id": int(row[1]),
                        "source_event_id": int(row[2]),
                        "source_type": str(row[3]),
                        "payload_json": row[4],
                        "attempts": int(row[5]) + 1,
                    }
                )
        return tuple(claimed)

    async def apply_claim(
        self,
        connection: Any,
        work: dict[str, object],
        *,
        formula_version: str,
    ) -> ProfileRefreshReceipt:
        outbox_id = int(work["outbox_id"])
        user_id = int(work["user_id"])
        source_event_id = int(work["source_event_id"])
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT event_uuid, event_type, resource_id, occurred_at, reason_code "
                "FROM user_behavior_event WHERE id = %s AND user_id = %s",
                (source_event_id, user_id),
            )
            event = await cursor.fetchone()
        if event is None:
            raise ValueError("profile outbox references a missing behavior event")
        as_of = event[3]
        events = await _read_events(connection, user_id=user_id, as_of=as_of)
        snapshot = compute_profile_snapshot(
            user_id=user_id,
            as_of=as_of,
            events=events,
            formula_version=formula_version,
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT profile_version FROM profile_replay_run "
                "WHERE user_id = %s AND as_of = %s AND formula_version = %s AND input_hash = %s",
                (user_id, _db_datetime(as_of), formula_version, snapshot.input_hash),
            )
            existing = await cursor.fetchone()
            await cursor.execute(
                "SELECT COALESCE(profile_version, 0) FROM user_profile WHERE user_id = %s",
                (user_id,),
            )
            current_row = await cursor.fetchone()
            current_version = int(current_row[0]) if current_row is not None else 0
            if existing is not None:
                target_version = int(existing[0])
                inserted_replay = False
            else:
                await cursor.execute(
                    "SELECT COALESCE(MAX(profile_version), 0) FROM profile_replay_run WHERE user_id = %s",
                    (user_id,),
                )
                max_row = await cursor.fetchone()
                target_version = max(current_version, int(max_row[0])) + 1
                await cursor.execute(
                    "INSERT INTO profile_replay_run "
                    "(user_id, as_of, formula_version, input_hash, profile_version, event_count, applied_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (user_id, _db_datetime(as_of), formula_version, snapshot.input_hash, target_version, snapshot.event_count, now),
                )
                inserted_replay = True
            changed = target_version > current_version
            if changed:
                await cursor.execute(
                    "UPDATE user_interest_tag SET positive_weight = 0, raw_positive_signal = 0, "
                    "source_count = 0, profile_version = %s WHERE user_id = %s",
                    (target_version, user_id),
                )
                await cursor.execute(
                    "UPDATE user_negative_preference SET negative_weight = 0, raw_negative_signal = 0, "
                    "source_count = 0, profile_version = %s WHERE user_id = %s",
                    (target_version, user_id),
                )
                await cursor.execute(
                    "INSERT INTO user_profile "
                    "(user_id, profile_version, profile_confidence, recent_focus_tag_id, topic_focus_strength, "
                    "reading_stage, reading_stage_confidence, updated_at) VALUES (%s, %s, %s, %s, %s, NULL, 0, %s) "
                    "AS new ON DUPLICATE KEY UPDATE profile_version = new.profile_version, "
                    "profile_confidence = new.profile_confidence, recent_focus_tag_id = new.recent_focus_tag_id, "
                    "topic_focus_strength = new.topic_focus_strength, reading_stage = new.reading_stage, "
                    "reading_stage_confidence = new.reading_stage_confidence, updated_at = new.updated_at",
                    (user_id, target_version, _decimal(snapshot.profile_confidence), snapshot.recent_focus_tag_id, _decimal(snapshot.topic_focus_strength), now),
                )
                for signal in snapshot.interests:
                    await cursor.execute(
                        "INSERT INTO user_interest_tag "
                        "(user_id, tag_id, positive_weight, raw_positive_signal, source_count, last_event_at, profile_version) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s) AS new ON DUPLICATE KEY UPDATE "
                        "positive_weight = new.positive_weight, raw_positive_signal = new.raw_positive_signal, "
                        "source_count = new.source_count, last_event_at = new.last_event_at, profile_version = new.profile_version",
                        (user_id, signal.tag_id, _decimal(signal.weight), _decimal(signal.raw_signal), signal.source_count, _db_datetime(signal.last_event_at), target_version),
                    )
                for signal in snapshot.negatives:
                    await cursor.execute(
                        "INSERT INTO user_negative_preference "
                        "(user_id, tag_id, reason_code, negative_weight, raw_negative_signal, source_count, expires_at, last_event_at, profile_version) "
                        "VALUES (%s, %s, %s, %s, %s, %s, NULL, %s, %s) AS new ON DUPLICATE KEY UPDATE "
                        "negative_weight = new.negative_weight, raw_negative_signal = new.raw_negative_signal, "
                        "source_count = new.source_count, last_event_at = new.last_event_at, profile_version = new.profile_version",
                        (user_id, signal.tag_id, signal.reason_code, _decimal(signal.weight), _decimal(signal.raw_signal), signal.source_count, _db_datetime(signal.last_event_at), target_version),
                    )
                if inserted_replay:
                    for replay_event in events:
                        delta = {
                            "event_type": replay_event.event_type,
                            "resource_id": replay_event.resource_id,
                            "tag_ids": [tag.tag_id for tag in replay_event.tags],
                            "as_of": as_of.isoformat(),
                        }
                        await cursor.execute(
                            "INSERT IGNORE INTO profile_change_log "
                            "(user_id, source_event_id, source_type, profile_version_before, profile_version_after, "
                            "delta_json, formula_version, created_at) VALUES (%s, %s, 'REPLAY', %s, %s, %s, %s, %s)",
                            (user_id, replay_event.event_id, max(0, target_version - 1), target_version, _canonical(delta), formula_version, now),
                        )
        return ProfileRefreshReceipt(
            outbox_id=outbox_id,
            user_id=user_id,
            source_event_id=source_event_id,
            profile_version=target_version,
            event_count=snapshot.event_count,
            input_hash=snapshot.input_hash,
            changed=changed,
        )

    async def mark_done(self, connection: Any, *, outbox_id: int) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        async with connection.cursor() as cursor:
            await cursor.execute(
                "UPDATE profile_update_outbox SET status = 'DONE', next_retry_at = NULL, "
                "locked_at = NULL, locked_by = NULL, last_error = NULL, updated_at = %s WHERE id = %s",
                (now, outbox_id),
            )

    async def mark_failed(
        self,
        connection: Any,
        *,
        outbox_id: int,
        error_code: str,
        dead: bool,
    ) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        status = "DEAD" if dead else "PENDING"
        next_retry = None if dead else now + timedelta(seconds=30)
        async with connection.cursor() as cursor:
            await cursor.execute(
                "UPDATE profile_update_outbox SET status = %s, next_retry_at = %s, locked_at = NULL, "
                "locked_by = NULL, last_error = %s, updated_at = %s WHERE id = %s",
                (status, next_retry, error_code[:1000], now, outbox_id),
            )


__all__ = ["MySQLProfileRefreshAdapter"]
