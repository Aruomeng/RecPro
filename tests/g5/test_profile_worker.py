from __future__ import annotations

import asyncio
import unittest

from backend.app.feedback.domain.public import ProfileRefreshReceipt
from backend.app.profile.application.refresh import ProfileOutboxWorker


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


class FakeRefreshPort:
    def __init__(
        self,
        *,
        fail: bool = False,
        starting_attempts: int = 1,
        empty_after_first: bool = False,
    ) -> None:
        self.fail = fail
        self.starting_attempts = starting_attempts
        self.empty_after_first = empty_after_first
        self.claims = 0
        self.done: list[int] = []
        self.failed: list[tuple[int, bool]] = []

    async def claim_pending(self, connection, **kwargs):
        self.claims += 1
        if self.empty_after_first and self.claims > 1:
            return ()
        return (
            {
                "outbox_id": 44,
                "user_id": 1001,
                "source_event_id": 77,
                "attempts": self.starting_attempts + self.claims - 1,
            },
        )

    async def apply_claim(self, connection, work, *, formula_version):
        if self.fail:
            raise RuntimeError("refresh failed")
        return ProfileRefreshReceipt(44, 1001, 77, 2, 6, "a" * 64, True)

    async def mark_done(self, connection, *, outbox_id):
        self.done.append(outbox_id)

    async def mark_failed(self, connection, *, outbox_id, error_code, dead):
        self.failed.append((outbox_id, dead))


class ProfileWorkerTests(unittest.TestCase):
    def test_worker_commits_profile_and_done_together(self) -> None:
        connections: list[FakeConnection] = []

        async def factory():
            connection = FakeConnection()
            connections.append(connection)
            return connection

        port = FakeRefreshPort()
        worker = ProfileOutboxWorker(
            connection_factory=factory,
            refresh_port=port,
            worker_id="g5-test-worker",
        )
        receipts = asyncio.run(worker.run_once(limit=1))
        self.assertEqual(1, len(receipts))
        self.assertEqual([44], port.done)
        self.assertEqual([], port.failed)
        self.assertTrue(any(connection.commits == 1 for connection in connections))
        self.assertTrue(all(connection.closed == 1 for connection in connections))

    def test_worker_does_not_reclaim_a_done_item(self) -> None:
        connections: list[FakeConnection] = []

        async def factory():
            connection = FakeConnection()
            connections.append(connection)
            return connection

        port = FakeRefreshPort(empty_after_first=True)
        worker = ProfileOutboxWorker(
            connection_factory=factory,
            refresh_port=port,
            worker_id="g5-test-worker",
        )
        first = asyncio.run(worker.run_once(limit=1))
        second = asyncio.run(worker.run_once(limit=1))
        self.assertEqual(1, len(first))
        self.assertEqual((), second)
        self.assertEqual(2, port.claims)
        self.assertEqual([44], port.done)

    def test_worker_records_retryable_failure_without_losing_claim(self) -> None:
        connections: list[FakeConnection] = []

        async def factory():
            connection = FakeConnection()
            connections.append(connection)
            return connection

        port = FakeRefreshPort(fail=True)
        worker = ProfileOutboxWorker(
            connection_factory=factory,
            refresh_port=port,
            worker_id="g5-test-worker",
            max_attempts=3,
        )
        self.assertEqual((), asyncio.run(worker.run_once(limit=1)))
        self.assertEqual([], port.done)
        self.assertEqual([(44, False)], port.failed)
        self.assertGreaterEqual(sum(connection.commits for connection in connections), 2)
        self.assertGreaterEqual(sum(connection.rollbacks for connection in connections), 1)

    def test_worker_retries_the_same_claim_without_losing_the_fact(self) -> None:
        connections: list[FakeConnection] = []

        async def factory():
            connection = FakeConnection()
            connections.append(connection)
            return connection

        port = FakeRefreshPort(fail=True)
        worker = ProfileOutboxWorker(
            connection_factory=factory,
            refresh_port=port,
            worker_id="g5-test-worker",
            max_attempts=3,
        )
        self.assertEqual((), asyncio.run(worker.run_once(limit=1)))
        self.assertEqual([(44, False)], port.failed)
        port.fail = False
        receipts = asyncio.run(worker.run_once(limit=1))
        self.assertEqual(1, len(receipts))
        self.assertEqual([44], port.done)
        self.assertEqual(2, port.claims)

    def test_worker_marks_max_attempt_failure_dead_and_keeps_row(self) -> None:
        connections: list[FakeConnection] = []

        async def factory():
            connection = FakeConnection()
            connections.append(connection)
            return connection

        port = FakeRefreshPort(fail=True, starting_attempts=3)
        worker = ProfileOutboxWorker(
            connection_factory=factory,
            refresh_port=port,
            worker_id="g5-test-worker",
            max_attempts=3,
        )
        self.assertEqual((), asyncio.run(worker.run_once(limit=1)))
        self.assertEqual([(44, True)], port.failed)
        self.assertEqual([], port.done)


if __name__ == "__main__":
    unittest.main()
