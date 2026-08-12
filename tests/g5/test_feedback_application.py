from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from backend.app.feedback.application.service import FeedbackApplicationService
from backend.app.feedback.domain.public import (
    BehaviorAppendCommand,
    BehaviorReceipt,
    FeedbackCommand,
    FeedbackReceipt,
    ImpressionCommand,
    ImpressionReceipt,
)
from backend.app.shared_kernel.contracts.enums import BehaviorEventType, FeedbackType, NegativeReasonCode


class FakeConnection:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed += 1


class FakeBehaviorPort:
    def __init__(self) -> None:
        self.commands: list[BehaviorAppendCommand] = []

    async def append_behavior(self, connection, command) -> BehaviorReceipt:
        self.commands.append(command)
        return BehaviorReceipt(command.event_uuid, 901 + len(self.commands), 1001, len(self.commands) > 1)


class FakeFeedbackStore:
    def __init__(self) -> None:
        self.impressions: list[ImpressionCommand] = []
        self.feedback: list[FeedbackCommand] = []

    async def find_item(self, connection, *, recommendation_item_id, user_id):
        if recommendation_item_id != 7 or user_id != 1001:
            return None
        return {
            "resource_id": 11,
            "resource_type": "PAPER",
            "availability_status": "AVAILABLE_ONLINE",
            "difficulty_level": 3,
        }

    async def find_impression(self, connection, *, impression_uuid, user_id, recommendation_item_id):
        return {"impression_id": 10, "impression_uuid": str(impression_uuid)}

    async def find_behavior_event(self, connection, *, event_uuid, user_id, recommendation_item_id):
        return None

    async def append_impression(self, connection, command):
        self.impressions.append(command)
        return ImpressionReceipt(command.impression_uuid, 10, 0, True, False)

    async def append_feedback(self, connection, *, command, resource_id, state, behavior_event_id):
        self.feedback.append(command)
        return FeedbackReceipt(command.feedback_uuid, 20, behavior_event_id, None, state, False)


def now() -> datetime:
    return datetime(2025, 12, 30, 12, 0, tzinfo=UTC)


class FeedbackApplicationTests(unittest.TestCase):
    def test_impression_and_behavior_commit_as_one_batch(self) -> None:
        connection = FakeConnection()
        behavior = FakeBehaviorPort()
        store = FakeFeedbackStore()
        service = FeedbackApplicationService(
            connection_factory=lambda: _resolved(connection),
            feedback_store=store,
            behavior_port=behavior,
        )
        command = ImpressionCommand(
            impression_uuid=uuid4(),
            recommendation_item_id=7,
            user_id=1001,
            position=1,
            rendered_at=now(),
            visible_started_at=now(),
            visible_ms=1500,
            max_visible_ratio=0.8,
        )

        receipt = asyncio.run(service.record_impression(command))

        self.assertEqual(10, receipt.impression_id)
        self.assertEqual(902, receipt.behavior_event_id)
        self.assertTrue(receipt.is_valid_exposure)
        self.assertEqual(1, connection.commits)
        self.assertEqual(0, connection.rollbacks)
        self.assertEqual(BehaviorEventType.RECOMMENDATION_IMPRESSION, behavior.commands[0].event_type)
        self.assertFalse(behavior.commands[0].enqueue_profile_update)

    def test_topic_feedback_appends_profile_outbox_and_resource_state(self) -> None:
        connection = FakeConnection()
        behavior = FakeBehaviorPort()
        store = FakeFeedbackStore()
        service = FeedbackApplicationService(
            connection_factory=lambda: _resolved(connection),
            feedback_store=store,
            behavior_port=behavior,
        )
        command = FeedbackCommand(
            feedback_uuid=uuid4(),
            recommendation_item_id=7,
            user_id=1001,
            feedback_type=FeedbackType.NOT_INTERESTED,
            impression_uuid=uuid4(),
            reason_code=NegativeReasonCode.TOPIC_NOT_INTERESTED,
            occurred_at=now(),
        )

        receipt = asyncio.run(service.record_feedback(command))

        self.assertEqual(20, receipt.feedback_id)
        self.assertEqual(902, receipt.behavior_event_id)
        self.assertEqual(1001, receipt.outbox_id)
        self.assertEqual("HIDDEN", receipt.resource_state["state_type"])
        self.assertEqual(1, connection.commits)
        self.assertEqual(BehaviorEventType.NOT_INTERESTED, behavior.commands[0].event_type)
        self.assertTrue(behavior.commands[0].enqueue_profile_update)

    def test_already_read_marks_only_the_target_resource_state(self) -> None:
        connection = FakeConnection()
        behavior = FakeBehaviorPort()
        store = FakeFeedbackStore()
        service = FeedbackApplicationService(
            connection_factory=lambda: _resolved(connection),
            feedback_store=store,
            behavior_port=behavior,
        )
        command = FeedbackCommand(
            feedback_uuid=uuid4(),
            recommendation_item_id=7,
            user_id=1001,
            feedback_type=FeedbackType.NOT_INTERESTED,
            impression_uuid=uuid4(),
            reason_code=NegativeReasonCode.ALREADY_READ,
            occurred_at=now(),
        )

        receipt = asyncio.run(service.record_feedback(command))

        self.assertEqual("READ", receipt.resource_state["state_type"])
        self.assertEqual(NegativeReasonCode.ALREADY_READ.value, behavior.commands[0].reason_code)
        self.assertTrue(behavior.commands[0].enqueue_profile_update)

    def test_invalid_borrow_rolls_back_without_behavior(self) -> None:
        connection = FakeConnection()
        behavior = FakeBehaviorPort()
        service = FeedbackApplicationService(
            connection_factory=lambda: _resolved(connection),
            feedback_store=FakeFeedbackStore(),
            behavior_port=behavior,
        )
        command = FeedbackCommand(
            feedback_uuid=uuid4(),
            recommendation_item_id=7,
            user_id=1001,
            feedback_type=FeedbackType.BORROW,
            occurred_at=now(),
        )
        with self.assertRaisesRegex(ValueError, "available BOOK"):
            asyncio.run(service.record_feedback(command))
        self.assertEqual(0, connection.commits)
        self.assertEqual(1, connection.rollbacks)
        self.assertEqual([], behavior.commands)

    def test_rate_and_reason_rules_are_deterministic(self) -> None:
        with self.assertRaises(ValueError):
            FeedbackCommand(
                feedback_uuid=uuid4(),
                recommendation_item_id=7,
                user_id=1001,
                feedback_type=FeedbackType.RATE,
                occurred_at=now(),
            )
        with self.assertRaises(ValueError):
            FeedbackCommand(
                feedback_uuid=uuid4(),
                recommendation_item_id=7,
                user_id=1001,
                feedback_type=FeedbackType.FAVORITE,
                rating=5,
                occurred_at=now(),
            )


async def _resolved(value):
    return value


if __name__ == "__main__":
    unittest.main()
