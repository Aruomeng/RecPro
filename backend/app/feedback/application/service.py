"""Transactional G5 exposure, feedback, and behavior application services."""

from __future__ import annotations

import inspect
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable
from uuid import NAMESPACE_URL, uuid5

from backend.app.feedback.domain.public import (
    BehaviorAppendCommand,
    BehaviorReceipt,
    FeedbackCommand,
    FeedbackReceipt,
    ImpressionCommand,
    ImpressionReceipt,
    feedback_event_type,
)
from backend.app.feedback.ports.public import FeedbackStorePort
from backend.app.profile.ports.public import BehaviorAppendPort
from backend.app.shared_kernel.contracts.enums import (
    BehaviorEventType,
    FeedbackType,
    NegativeReasonCode,
)


ConnectionFactory = Callable[[], Awaitable[Any]]


async def _close(connection: Any) -> None:
    result = connection.close()
    if inspect.isawaitable(result):
        await result


def _session_id(seed: str) -> Any:
    return uuid5(NAMESPACE_URL, f"g5-feedback-session:{seed}")


def _state_for(command: FeedbackCommand) -> dict[str, object] | None:
    reason = command.reason_code
    if command.feedback_type is FeedbackType.FAVORITE:
        return {"state_type": "FAVORITED", "suppress_until": None}
    if command.feedback_type is FeedbackType.BORROW:
        return {"state_type": "BORROWED", "suppress_until": None}
    if command.feedback_type is FeedbackType.RATE and (command.rating or 0) >= 3:
        return None
    if reason is NegativeReasonCode.ALREADY_READ:
        return {"state_type": "READ", "suppress_until": None}
    if reason is NegativeReasonCode.NOT_NOW:
        return {"state_type": "NOT_NOW", "suppress_until": command.occurred_at + timedelta(days=7)}
    if reason is NegativeReasonCode.REPEATED:
        return {"state_type": "DUPLICATE_SUPPRESS", "suppress_until": command.occurred_at + timedelta(days=30)}
    if reason is NegativeReasonCode.LOW_QUALITY:
        return {"state_type": "HIDDEN", "suppress_until": None}
    if reason is NegativeReasonCode.TOPIC_NOT_INTERESTED:
        return {"state_type": "HIDDEN", "suppress_until": command.occurred_at + timedelta(days=30)}
    if command.feedback_type is FeedbackType.RATE and (command.rating or 0) <= 2:
        return {"state_type": "HIDDEN", "suppress_until": command.occurred_at + timedelta(days=30)}
    return {"state_type": "HIDDEN", "suppress_until": command.occurred_at + timedelta(days=7)}


def _as_aware(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("stored behavior event occurred_at is invalid")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class BehaviorApplicationService:
    """Own the connection transaction for one direct behavior command."""

    def __init__(
        self,
        *,
        connection_factory: ConnectionFactory,
        append_port: BehaviorAppendPort,
        ownership_reader: FeedbackStorePort | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._append_port = append_port
        self._ownership_reader = ownership_reader

    async def close(self) -> None:
        """Close an explicitly composed connection factory, if applicable."""

        close = getattr(self._connection_factory, "close", None)
        if not callable(close):
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    def runtime_metrics(self) -> dict[str, object] | None:
        snapshot = getattr(self._connection_factory, "snapshot", None)
        if not callable(snapshot):
            return None
        value = snapshot()
        as_dict = getattr(value, "as_dict", None)
        if callable(as_dict):
            value = as_dict()
        return dict(value) if isinstance(value, dict) else None

    async def append(self, command: BehaviorAppendCommand) -> BehaviorReceipt:
        connection = await self._connection_factory()
        try:
            if self._ownership_reader is not None and command.recommendation_item_id is not None:
                item = await self._ownership_reader.find_item(
                    connection,
                    recommendation_item_id=command.recommendation_item_id,
                    user_id=command.user_id,
                )
                if item is None:
                    raise LookupError("recommendation item does not belong to user")
                if command.impression_uuid is not None:
                    impression = await self._ownership_reader.find_impression(
                        connection,
                        impression_uuid=command.impression_uuid,
                        user_id=command.user_id,
                        recommendation_item_id=command.recommendation_item_id,
                    )
                    if impression is None:
                        raise ValueError("impression does not belong to user and recommendation item")
            receipt = await self._append_port.append_behavior(connection, command)
            await connection.commit()
            return receipt
        except BaseException:
            await connection.rollback()
            raise
        finally:
            await _close(connection)


class FeedbackApplicationService:
    """Coordinate Feedback-owned facts and Profile behavior facts atomically."""

    def __init__(
        self,
        *,
        connection_factory: ConnectionFactory,
        feedback_store: FeedbackStorePort,
        behavior_port: BehaviorAppendPort,
    ) -> None:
        self._connection_factory = connection_factory
        self._feedback_store = feedback_store
        self._behavior_port = behavior_port

    async def close(self) -> None:
        """Close an explicitly composed connection factory, if applicable."""

        close = getattr(self._connection_factory, "close", None)
        if not callable(close):
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    def runtime_metrics(self) -> dict[str, object] | None:
        snapshot = getattr(self._connection_factory, "snapshot", None)
        if not callable(snapshot):
            return None
        value = snapshot()
        as_dict = getattr(value, "as_dict", None)
        if callable(as_dict):
            value = as_dict()
        return dict(value) if isinstance(value, dict) else None

    async def record_impression(self, command: ImpressionCommand) -> ImpressionReceipt:
        connection = await self._connection_factory()
        try:
            item = await self._feedback_store.find_item(
                connection,
                recommendation_item_id=command.recommendation_item_id,
                user_id=command.user_id,
            )
            if item is None:
                raise LookupError("recommendation item does not belong to user")
            receipt = await self._feedback_store.append_impression(connection, command)
            behavior = await self._behavior_port.append_behavior(
                connection,
                BehaviorAppendCommand(
                    event_uuid=command.impression_uuid,
                    user_id=command.user_id,
                    session_id=_session_id(str(command.impression_uuid)),
                    event_type=BehaviorEventType.RECOMMENDATION_IMPRESSION,
                    occurred_at=command.rendered_at,
                    resource_id=int(item["resource_id"]),
                    recommendation_item_id=command.recommendation_item_id,
                    impression_uuid=command.impression_uuid,
                    visible_ratio=command.max_visible_ratio,
                    dwell_ms=command.visible_ms,
                    position=command.position,
                    enqueue_profile_update=False,
                ),
            )
            await connection.commit()
            return ImpressionReceipt(
                impression_uuid=receipt.impression_uuid,
                impression_id=receipt.impression_id,
                behavior_event_id=behavior.event_id,
                is_valid_exposure=receipt.is_valid_exposure,
                replayed=receipt.replayed and behavior.replayed,
            )
        except BaseException:
            await connection.rollback()
            raise
        finally:
            await _close(connection)

    async def record_feedback(self, command: FeedbackCommand) -> FeedbackReceipt:
        connection = await self._connection_factory()
        try:
            item = await self._feedback_store.find_item(
                connection,
                recommendation_item_id=command.recommendation_item_id,
                user_id=command.user_id,
            )
            if item is None:
                raise LookupError("recommendation item does not belong to user")
            existing_event = await self._feedback_store.find_behavior_event(
                connection,
                event_uuid=command.feedback_uuid,
                user_id=command.user_id,
                recommendation_item_id=command.recommendation_item_id,
            )
            if existing_event is not None:
                expected_event_type = feedback_event_type(command).value
                expected_impression = (
                    str(command.impression_uuid) if command.impression_uuid is not None else None
                )
                expected_reason = command.reason_code.value if command.reason_code is not None else None
                if (
                    existing_event["event_type"] != expected_event_type
                    or existing_event["resource_id"] != int(item["resource_id"])
                    or existing_event["impression_uuid"] != expected_impression
                    or existing_event["rating"] != command.rating
                    or existing_event["reason_code"] != expected_reason
                ):
                    raise ValueError("feedback event identity or payload conflict")
                # The public feedback DTO intentionally lets the server assign its
                # business timestamp. Reuse the persisted timestamp on a UUID retry
                # so idempotency does not turn a safe replay into a payload conflict.
                command = replace(command, occurred_at=_as_aware(existing_event["occurred_at"]))
            if command.feedback_type in {
                FeedbackType.REJECT,
                FeedbackType.NOT_INTERESTED,
                FeedbackType.RATE,
            }:
                if command.impression_uuid is None:
                    raise ValueError("this feedback type requires impression_uuid")
                impression = await self._feedback_store.find_impression(
                    connection,
                    impression_uuid=command.impression_uuid,
                    user_id=command.user_id,
                    recommendation_item_id=command.recommendation_item_id,
                )
                if impression is None:
                    raise ValueError("impression does not belong to user and recommendation item")
            if command.feedback_type is FeedbackType.BORROW and (
                item["resource_type"] != "BOOK" or item["availability_status"] != "AVAILABLE_BORROW"
            ):
                raise ValueError("BORROW requires an available BOOK resource")
            if command.reason_code is NegativeReasonCode.TOPIC_NOT_INTERESTED and command.feedback_type not in {
                FeedbackType.REJECT,
                FeedbackType.NOT_INTERESTED,
            }:
                raise ValueError("TOPIC_NOT_INTERESTED requires REJECT or NOT_INTERESTED")
            if command.reason_code in {NegativeReasonCode.TOO_BASIC, NegativeReasonCode.TOO_ADVANCED} and item["difficulty_level"] is None:
                raise ValueError("difficulty reason requires resource difficulty metadata")
            behavior = await self._behavior_port.append_behavior(
                connection,
                BehaviorAppendCommand(
                    event_uuid=command.feedback_uuid,
                    user_id=command.user_id,
                    session_id=_session_id(str(command.impression_uuid or command.feedback_uuid)),
                    event_type=feedback_event_type(command),
                    occurred_at=command.occurred_at,
                    resource_id=int(item["resource_id"]),
                    recommendation_item_id=command.recommendation_item_id,
                    impression_uuid=command.impression_uuid,
                    rating=command.rating,
                    reason_code=command.reason_code.value if command.reason_code else None,
                ),
            )
            receipt = await self._feedback_store.append_feedback(
                connection,
                command=command,
                resource_id=int(item["resource_id"]),
                state=_state_for(command),
                behavior_event_id=behavior.event_id,
            )
            await connection.commit()
            return FeedbackReceipt(
                feedback_uuid=receipt.feedback_uuid,
                feedback_id=receipt.feedback_id,
                behavior_event_id=receipt.behavior_event_id,
                outbox_id=behavior.outbox_id,
                resource_state=receipt.resource_state,
                replayed=receipt.replayed and behavior.replayed,
            )
        except BaseException:
            await connection.rollback()
            raise
        finally:
            await _close(connection)


__all__ = ["BehaviorApplicationService", "FeedbackApplicationService"]
