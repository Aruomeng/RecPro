"""Append-only MySQL behavior facts and profile outbox adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from backend.app.feedback.domain.public import BehaviorAppendCommand, BehaviorReceipt
from backend.app.observability.domain.public import StateTransition, transition_uuid
from backend.app.observability.ports.public import StateTransitionSink
from backend.app.profile.ports.public import BehaviorAppendPort


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json(value: object) -> object:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return value


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is not None and value.utcoffset() is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


def _decimal(value: float | None) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


class MySQLBehaviorAppender(BehaviorAppendPort):
    """Insert behavior facts and optional profile outbox rows without commits."""

    def __init__(self, *, transition_sink: StateTransitionSink | None = None) -> None:
        self._transition_sink = transition_sink

    async def append_behavior(self, connection: Any, command: BehaviorAppendCommand) -> BehaviorReceipt:
        created_at = datetime.now(UTC).replace(tzinfo=None)
        tag_json = _canonical(list(command.tag_evidence))
        async with connection.cursor() as cursor:
            await cursor.execute(
                "INSERT IGNORE INTO user_behavior_event "
                "(event_uuid, user_id, session_id, event_type, resource_id, recommendation_item_id, "
                "task_id, impression_uuid, query_text, rating, dwell_ms, visible_ratio, position, reason_code, "
                "tag_evidence_json, occurred_at, created_at) VALUES "
                "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    str(command.event_uuid),
                    command.user_id,
                    str(command.session_id),
                    command.event_type.value,
                    command.resource_id,
                    command.recommendation_item_id,
                    str(command.task_id) if command.task_id else None,
                    str(command.impression_uuid) if command.impression_uuid else None,
                    command.query_text,
                    _decimal(command.rating),
                    command.dwell_ms,
                    _decimal(command.visible_ratio),
                    command.position,
                    command.reason_code,
                    tag_json,
                    _naive_utc(command.occurred_at),
                    created_at,
                ),
            )
            inserted = cursor.rowcount == 1
            await cursor.execute(
                "SELECT id, event_uuid, user_id, session_id, event_type, resource_id, "
                "recommendation_item_id, task_id, impression_uuid, query_text, rating, dwell_ms, "
                "visible_ratio, position, reason_code, tag_evidence_json, occurred_at "
                "FROM user_behavior_event WHERE event_uuid = %s",
                (str(command.event_uuid),),
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError("behavior event could not be resolved after append")
            expected = (
                str(command.event_uuid),
                command.user_id,
                str(command.session_id),
                command.event_type.value,
                command.resource_id,
                command.recommendation_item_id,
                str(command.task_id) if command.task_id else None,
                str(command.impression_uuid) if command.impression_uuid else None,
                command.query_text,
                _decimal(command.rating),
                command.dwell_ms,
                _decimal(command.visible_ratio),
                command.position,
                command.reason_code,
            )
            actual = tuple(row[1:15])
            if actual != expected:
                raise ValueError("behavior event identity or payload conflict")
            if _canonical(_json(row[15])) != tag_json:
                raise ValueError("behavior event tag evidence conflict")
            if _naive_utc(row[16]) != _naive_utc(command.occurred_at):
                raise ValueError("behavior event occurred_at conflict")
            event_id = int(row[0])
            outbox_id: int | None = None
            if command.enqueue_profile_update:
                payload = {
                    "event_uuid": str(command.event_uuid),
                    "event_type": command.event_type.value,
                    "occurred_at": command.occurred_at.isoformat(),
                    "resource_id": command.resource_id,
                    "reason_code": command.reason_code,
                }
                await cursor.execute(
                    "INSERT IGNORE INTO profile_update_outbox "
                    "(user_id, source_event_id, source_type, payload_json, status, created_at, updated_at) "
                    "VALUES (%s, %s, 'BEHAVIOR', %s, 'PENDING', %s, %s)",
                    (command.user_id, event_id, _canonical(payload), created_at, created_at),
                )
                outbox_inserted = cursor.rowcount == 1
                await cursor.execute(
                    "SELECT id, status, attempts FROM profile_update_outbox "
                    "WHERE source_event_id = %s AND source_type = 'BEHAVIOR'",
                    (event_id,),
                )
                outbox = await cursor.fetchone()
                if outbox is None:
                    raise ValueError("profile outbox could not be resolved after append")
                outbox_id = int(outbox[0])
                if outbox_inserted and self._transition_sink is not None:
                    aggregate_id = str(outbox_id)
                    await self._transition_sink.append(
                        connection,
                        StateTransition(
                            transition_uuid=transition_uuid(
                                aggregate_type="PROFILE_OUTBOX",
                                aggregate_id=aggregate_id,
                                transition_type="CREATED",
                                version_after=1,
                                causation_ref=f"BEHAVIOR:{event_id}",
                            ),
                            module_name="profile",
                            aggregate_type="PROFILE_OUTBOX",
                            aggregate_id=aggregate_id,
                            transition_type="CREATED",
                            from_state=None,
                            to_state="PENDING",
                            version_before=None,
                            version_after=1,
                            causation_ref=f"BEHAVIOR:{event_id}",
                            actor_type="SYSTEM",
                            actor_ref="behavior-appender",
                            detail={
                                "source_event_id": event_id,
                                "source_type": "BEHAVIOR",
                                "attempts": 0,
                            },
                            created_at=created_at.replace(tzinfo=UTC),
                        ),
                    )
        return BehaviorReceipt(
            event_uuid=command.event_uuid,
            event_id=event_id,
            outbox_id=outbox_id,
            replayed=not inserted,
        )


__all__ = ["MySQLBehaviorAppender"]
