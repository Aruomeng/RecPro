from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime
from uuid import UUID

from backend.app.feedback.application.service import FeedbackApplicationService
from backend.app.feedback.domain.public import (
    BehaviorAppendCommand,
    BehaviorReceipt,
    FeedbackCommand,
    FeedbackReceipt,
    ImpressionCommand,
    ImpressionReceipt,
    ProfileRefreshReceipt,
)
from backend.app.profile.application.refresh import ProfileOutboxWorker
from backend.app.shared_kernel.contracts.enums import (
    BehaviorEventType,
    FeedbackType,
    NegativeReasonCode,
)


class InMemoryG5Connection:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed += 1


class InMemoryG5Store:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state

    async def find_item(self, connection, *, recommendation_item_id, user_id):
        if recommendation_item_id != 7 or user_id != 1001:
            return None
        return {
            "resource_id": 11,
            "resource_type": "BOOK",
            "availability_status": "AVAILABLE_BORROW",
            "difficulty_level": 3,
        }

    async def find_impression(self, connection, *, impression_uuid, user_id, recommendation_item_id):
        return self.state.get("impression")

    async def find_behavior_event(self, connection, *, event_uuid, user_id, recommendation_item_id):
        return None

    async def append_impression(self, connection, command):
        receipt = ImpressionReceipt(command.impression_uuid, 10, 0, True, False)
        self.state["impression"] = {"impression_id": receipt.impression_id}
        return receipt

    async def append_feedback(self, connection, *, command, resource_id, state, behavior_event_id):
        self.state["feedback"] = command
        return FeedbackReceipt(command.feedback_uuid, 20, behavior_event_id, None, state, False)


class InMemoryBehaviorPort:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state
        self.next_event_id = 100

    async def append_behavior(self, connection, command: BehaviorAppendCommand) -> BehaviorReceipt:
        self.next_event_id += 1
        self.state.setdefault("events", []).append(command)
        outbox_id = None
        if command.enqueue_profile_update:
            outbox_id = 500 + len(self.state.setdefault("outbox", []))
            self.state["outbox"].append(
                {
                    "outbox_id": outbox_id,
                    "user_id": command.user_id,
                    "source_event_id": self.next_event_id,
                    "attempts": 1,
                    "status": "PENDING",
                }
            )
        return BehaviorReceipt(command.event_uuid, self.next_event_id, outbox_id, False)


class InMemoryRefreshPort:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state

    async def claim_pending(self, connection, **kwargs):
        for item in self.state["outbox"]:
            if item["status"] == "PENDING":
                item["status"] = "PROCESSING"
                return (item.copy(),)
        return ()

    async def apply_claim(self, connection, work, *, formula_version):
        version = int(self.state.get("profile_version", 0)) + 1
        self.state["profile_version"] = version
        event_count = len(self.state["events"])
        change_log = self.state.setdefault("change_log", [])
        change_log.append(
            {
                "profile_version_before": version - 1,
                "profile_version_after": version,
                "source_event_id": work["source_event_id"],
                "formula_version": formula_version,
            }
        )
        return ProfileRefreshReceipt(
            int(work["outbox_id"]),
            int(work["user_id"]),
            int(work["source_event_id"]),
            version,
            event_count,
            "a" * 64,
            True,
        )

    async def mark_done(self, connection, *, outbox_id):
        for item in self.state["outbox"]:
            if item["outbox_id"] == outbox_id:
                item["status"] = "DONE"

    async def mark_failed(self, connection, **kwargs):
        raise AssertionError("the direct A23 path must not fail")


def _now() -> datetime:
    return datetime(2026, 8, 12, 8, 0, tzinfo=UTC)


class FeedbackProfileVersionTests(unittest.TestCase):
    def test_feedback_to_worker_increments_profile_and_appends_change_log(self) -> None:
        state: dict[str, object] = {"events": [], "outbox": [], "change_log": []}
        connections: list[InMemoryG5Connection] = []

        async def factory() -> InMemoryG5Connection:
            connection = InMemoryG5Connection(state)
            connections.append(connection)
            return connection

        service = FeedbackApplicationService(
            connection_factory=factory,
            feedback_store=InMemoryG5Store(state),
            behavior_port=InMemoryBehaviorPort(state),
        )
        impression_uuid = UUID("11111111-1111-1111-1111-111111111111")
        asyncio.run(
            service.record_impression(
                ImpressionCommand(
                    impression_uuid=impression_uuid,
                    recommendation_item_id=7,
                    user_id=1001,
                    position=1,
                    rendered_at=_now(),
                    visible_started_at=_now(),
                    visible_ms=1500,
                    max_visible_ratio=0.8,
                )
            )
        )
        feedback = asyncio.run(
            service.record_feedback(
                FeedbackCommand(
                    feedback_uuid=UUID("22222222-2222-2222-2222-222222222222"),
                    recommendation_item_id=7,
                    user_id=1001,
                    feedback_type=FeedbackType.NOT_INTERESTED,
                    impression_uuid=impression_uuid,
                    reason_code=NegativeReasonCode.TOPIC_NOT_INTERESTED,
                    occurred_at=_now(),
                )
            )
        )
        self.assertIsNotNone(feedback.outbox_id)
        self.assertEqual(1, len(state["outbox"]))

        receipts = asyncio.run(
            ProfileOutboxWorker(
                connection_factory=factory,
                refresh_port=InMemoryRefreshPort(state),
                worker_id="a23-offline-worker",
            ).run_once(limit=1)
        )

        self.assertEqual(1, len(receipts))
        self.assertEqual(1, state["profile_version"])
        self.assertEqual("DONE", state["outbox"][0]["status"])
        self.assertEqual(1, len(state["change_log"]))
        self.assertEqual(0, state["change_log"][0]["profile_version_before"])
        self.assertEqual(1, state["change_log"][0]["profile_version_after"])
        self.assertGreaterEqual(len([c for c in connections if c.commits]), 4)


if __name__ == "__main__":
    unittest.main()
