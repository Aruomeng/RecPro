"""Append-only exposure/feedback facts and controlled resource-state projection."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from backend.app.feedback.domain.public import (
    FeedbackCommand,
    FeedbackReceipt,
    ImpressionCommand,
    ImpressionReceipt,
)
from backend.app.feedback.ports.public import FeedbackStorePort
from backend.app.observability.domain.public import StateTransition, transition_uuid
from backend.app.observability.ports.public import StateTransitionSink


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decimal(value: float | None) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is not None and value.utcoffset() is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


class MySQLFeedbackStore(FeedbackStorePort):
    """Use a caller-owned transaction for all feedback-owned facts."""

    def __init__(self, *, transition_sink: StateTransitionSink | None = None) -> None:
        self._transition_sink = transition_sink

    async def find_item(
        self,
        connection: Any,
        *,
        recommendation_item_id: int,
        user_id: int,
    ) -> dict[str, object] | None:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT ri.id, ri.resource_id, rr.user_id, rc.resource_type, "
                "rc.availability_status, rc.difficulty_level, rr.created_at "
                "FROM recommendation_item AS ri "
                "JOIN recommendation_record AS rr ON rr.id = ri.record_id "
                "JOIN resource_catalog AS rc ON rc.id = ri.resource_id "
                "WHERE ri.id = %s AND rr.user_id = %s",
                (recommendation_item_id, user_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "recommendation_item_id": int(row[0]),
            "resource_id": int(row[1]),
            "user_id": int(row[2]),
            "resource_type": str(row[3]),
            "availability_status": str(row[4]),
            "difficulty_level": int(row[5]) if row[5] is not None else None,
            "record_created_at": row[6],
        }

    async def find_impression(
        self,
        connection: Any,
        *,
        impression_uuid,
        user_id: int,
        recommendation_item_id: int,
    ) -> dict[str, object] | None:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT id, impression_uuid, recommendation_item_id, user_id, rendered_at, "
                "visible_ms, max_visible_ratio, is_valid_exposure "
                "FROM recommendation_impression WHERE impression_uuid = %s",
                (str(impression_uuid),),
            )
            row = await cursor.fetchone()
        if row is None or int(row[2]) != recommendation_item_id or int(row[3]) != user_id:
            return None
        return {
            "impression_id": int(row[0]),
            "impression_uuid": str(row[1]),
            "recommendation_item_id": int(row[2]),
            "user_id": int(row[3]),
            "rendered_at": row[4],
            "visible_ms": int(row[5]),
            "max_visible_ratio": float(row[6]),
            "is_valid_exposure": bool(row[7]),
        }

    async def find_behavior_event(
        self,
        connection: Any,
        *,
        event_uuid,
        user_id: int,
        recommendation_item_id: int,
    ) -> dict[str, object] | None:
        """Read an existing derived event so server-timestamped retries replay safely."""

        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT event_uuid, user_id, event_type, resource_id, recommendation_item_id, "
                "impression_uuid, rating, reason_code, occurred_at "
                "FROM user_behavior_event WHERE event_uuid = %s",
                (str(event_uuid),),
            )
            row = await cursor.fetchone()
        if row is None or int(row[1]) != user_id or int(row[4]) != recommendation_item_id:
            return None
        return {
            "event_uuid": str(row[0]),
            "user_id": int(row[1]),
            "event_type": str(row[2]),
            "resource_id": int(row[3]) if row[3] is not None else None,
            "recommendation_item_id": int(row[4]),
            "impression_uuid": str(row[5]) if row[5] is not None else None,
            "rating": float(row[6]) if row[6] is not None else None,
            "reason_code": str(row[7]) if row[7] is not None else None,
            "occurred_at": row[8],
        }

    async def append_impression(
        self,
        connection: Any,
        command: ImpressionCommand,
    ) -> ImpressionReceipt:
        created_at = datetime.now(UTC).replace(tzinfo=None)
        valid = command.visible_ms >= 1000 and command.max_visible_ratio >= 0.5
        async with connection.cursor() as cursor:
            await cursor.execute(
                "INSERT IGNORE INTO recommendation_impression "
                "(impression_uuid, recommendation_item_id, user_id, position, rendered_at, "
                "visible_started_at, visible_ms, max_visible_ratio, is_valid_exposure, clicked_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)",
                (
                    str(command.impression_uuid),
                    command.recommendation_item_id,
                    command.user_id,
                    command.position,
                    _naive_utc(command.rendered_at),
                    _naive_utc(command.visible_started_at) if command.visible_started_at else None,
                    command.visible_ms,
                    _decimal(command.max_visible_ratio),
                    valid,
                ),
            )
            inserted = cursor.rowcount == 1
            await cursor.execute(
                "SELECT id, impression_uuid, recommendation_item_id, user_id, position, rendered_at, "
                "visible_started_at, visible_ms, max_visible_ratio, is_valid_exposure "
                "FROM recommendation_impression WHERE impression_uuid = %s",
                (str(command.impression_uuid),),
            )
            row = await cursor.fetchone()
        if row is None:
            raise ValueError("impression could not be resolved after append")
        expected = (
            str(command.impression_uuid),
            command.recommendation_item_id,
            command.user_id,
            command.position,
            _naive_utc(command.rendered_at),
            _naive_utc(command.visible_started_at) if command.visible_started_at else None,
            command.visible_ms,
            _decimal(command.max_visible_ratio),
            valid,
        )
        actual = (
            str(row[1]),
            int(row[2]),
            int(row[3]),
            int(row[4]),
            _naive_utc(row[5]),
            _naive_utc(row[6]) if row[6] else None,
            int(row[7]),
            Decimal(str(row[8])),
            bool(row[9]),
        )
        if actual != expected:
            raise ValueError("impression identity or payload conflict")
        return ImpressionReceipt(
            impression_uuid=command.impression_uuid,
            impression_id=int(row[0]),
            behavior_event_id=0,
            is_valid_exposure=bool(row[9]),
            replayed=not inserted,
        )

    async def append_feedback(
        self,
        connection: Any,
        *,
        command: FeedbackCommand,
        resource_id: int,
        state: dict[str, object] | None,
        behavior_event_id: int,
    ) -> FeedbackReceipt:
        created_at = datetime.now(UTC).replace(tzinfo=None)
        reason = command.reason_code.value if command.reason_code is not None else None
        async with connection.cursor() as cursor:
            await cursor.execute(
                "INSERT IGNORE INTO recommendation_feedback "
                "(feedback_uuid, recommendation_item_id, user_id, impression_uuid, feedback_type, "
                "reason_code, rating, content, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    str(command.feedback_uuid),
                    command.recommendation_item_id,
                    command.user_id,
                    str(command.impression_uuid) if command.impression_uuid else None,
                    command.feedback_type.value,
                    reason,
                    _decimal(command.rating),
                    command.content,
                    created_at,
                ),
            )
            inserted = cursor.rowcount == 1
            await cursor.execute(
                "SELECT id, feedback_uuid, recommendation_item_id, user_id, impression_uuid, "
                "feedback_type, reason_code, rating, content FROM recommendation_feedback "
                "WHERE feedback_uuid = %s",
                (str(command.feedback_uuid),),
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError("feedback could not be resolved after append")
            expected = (
                str(command.feedback_uuid),
                command.recommendation_item_id,
                command.user_id,
                str(command.impression_uuid) if command.impression_uuid else None,
                command.feedback_type.value,
                reason,
                _decimal(command.rating),
                command.content,
            )
            actual = (
                str(row[1]),
                int(row[2]),
                int(row[3]),
                str(row[4]) if row[4] is not None else None,
                str(row[5]),
                str(row[6]) if row[6] is not None else None,
                Decimal(str(row[7])) if row[7] is not None else None,
                row[8],
            )
            if actual != expected:
                raise ValueError("feedback identity or payload conflict")
            state_snapshot: dict[str, object] | None = None
            if state is not None:
                suppress_until = state.get("suppress_until")
                if isinstance(suppress_until, datetime):
                    suppress_until = _naive_utc(suppress_until)
                await cursor.execute(
                    "SELECT suppress_until, source_event_id, last_feedback_at, state_version "
                    "FROM user_resource_state WHERE user_id = %s AND resource_id = %s AND state_type = %s",
                    (command.user_id, resource_id, state["state_type"]),
                )
                existing_state = await cursor.fetchone()
                if existing_state is None:
                    state_version = 1
                    await cursor.execute(
                        "INSERT INTO user_resource_state "
                        "(user_id, resource_id, state_type, suppress_until, source_event_id, last_feedback_at, state_version) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (command.user_id, resource_id, state["state_type"], suppress_until, behavior_event_id, _naive_utc(command.occurred_at), state_version),
                    )
                    version_before = None
                elif int(existing_state[1]) == behavior_event_id:
                    state_version = int(existing_state[3])
                    version_before = None
                else:
                    state_version = int(existing_state[3]) + 1
                    await cursor.execute(
                        "UPDATE user_resource_state SET suppress_until = %s, source_event_id = %s, "
                        "last_feedback_at = %s, state_version = %s WHERE user_id = %s AND resource_id = %s AND state_type = %s",
                        (suppress_until, behavior_event_id, _naive_utc(command.occurred_at), state_version, command.user_id, resource_id, state["state_type"]),
                    )
                    version_before = int(existing_state[3])
                should_audit_state = self._transition_sink is not None and (
                    existing_state is None or version_before is not None
                )
                if should_audit_state:
                    aggregate_id = f"{command.user_id}:{resource_id}:{state['state_type']}"
                    is_created = existing_state is None
                    before_state = None if is_created else str(state["state_type"])
                    transition_type = "CREATED" if is_created else "UPDATED"
                    await self._transition_sink.append(
                        connection,
                        StateTransition(
                            transition_uuid=transition_uuid(
                                aggregate_type="USER_RESOURCE_STATE",
                                aggregate_id=aggregate_id,
                                transition_type=transition_type,
                                version_after=state_version,
                                causation_ref=f"BEHAVIOR:{behavior_event_id}",
                            ),
                            module_name="feedback",
                            aggregate_type="USER_RESOURCE_STATE",
                            aggregate_id=aggregate_id,
                            transition_type=transition_type,
                            from_state=before_state,
                            to_state=str(state["state_type"]),
                            version_before=version_before,
                            version_after=state_version,
                            causation_ref=f"BEHAVIOR:{behavior_event_id}",
                            actor_type="SYSTEM",
                            actor_ref="feedback-service",
                            detail={
                                "suppress_until": suppress_until.isoformat() if isinstance(suppress_until, datetime) else None,
                                "source_event_id": behavior_event_id,
                                "last_feedback_at": _naive_utc(command.occurred_at).isoformat(),
                            },
                            created_at=created_at.replace(tzinfo=UTC),
                        ),
                    )
                state_snapshot = {
                    "state_type": state["state_type"],
                    "suppress_until": suppress_until,
                    "source_event_id": behavior_event_id,
                    "last_feedback_at": _naive_utc(command.occurred_at).isoformat(),
                    "state_version": state_version,
                }
        return FeedbackReceipt(
            feedback_uuid=command.feedback_uuid,
            feedback_id=int(row[0]),
            behavior_event_id=behavior_event_id,
            outbox_id=None,
            resource_state=state_snapshot,
            replayed=not inserted,
        )


__all__ = ["MySQLFeedbackStore"]
